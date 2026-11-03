"""Shared pieces of the dashboard: colours, map layers, chart styling and cached images."""
import json
import math

import pandas as pd
import plotly.graph_objects as go
import pydeck as pdk
import streamlit as st

from analysis import PORT_POSITIONS
from data import radar_image_uri, thumbnail_uri

SURFACE = "#1a1a19"
INK = "#f0efec"
INK_SECONDARY = "#c3c2b7"
MUTED = "#898781"
GRID = "#2c2c2a"
AXIS = "#383835"
FONT = "system-ui, -apple-system, Segoe UI, sans-serif"

SHIP_RGB = [57, 135, 229]
FIXED_RGB = [201, 133, 0]
UNCERTAIN_RGB = [137, 135, 129]
DARK_RGB = [208, 59, 59]
RING_RGB = [240, 239, 236]
SHIP_HEX, FIXED_HEX, UNCERTAIN_HEX, DARK_HEX = "#3987e5", "#c98500", "#898781", "#d03b3b"

# Validated categorical order for the dark surface. Assigned by sorted name so a series keeps its colour.
SERIES_COLOURS = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"]
# Ordered classes use one hue, getting lighter as ships get bigger.
SIZE_RAMP = {"tiny": "#184f95", "small": "#256abf", "medium": "#3987e5", "large": "#6da7ec", "very_large": "#9ec5f4"}

MAP_HEIGHT_PX = 500
MAP_FIT_PX = 400
FLAG_COLUMN_PX = 100  # wide enough for "Not reported"
TOOLTIP_STYLE = {"backgroundColor": SURFACE, "color": INK, "fontSize": "13px"}
ATTRIBUTION = "Contains modified Copernicus Sentinel data (2026). Base map: OpenStreetMap, CARTO."
GFW_ATTRIBUTION = "[Powered by Global Fishing Watch.](https://globalfishingwatch.org)"
# For the pages shown with st.iframe. Streamlit embeds those through srcdoc, where location.origin is "null" but a worker's is
# the real origin. MapLibre drops worker messages whose origin doesn't match its own, leaving a blank map, so translate them.
_SRCDOC_MAP_FIX_JS = """(() => {
  const post = Worker.prototype.postMessage;
  Worker.prototype.postMessage = function (message, options) {
    return post.call(this, message && message.origin === location.origin ? { ...message, origin:window.origin } : message, options);
  };
  const listen = Worker.prototype.addEventListener;
  Worker.prototype.addEventListener = function (type, listener, options) {
    const translated = event => { if (event.data && event.data.origin === window.origin) event.data.origin = location.origin; listener(event); };
    return listen.call(this, type, type === "message" ? translated : listener, options);
  };
})();"""
# The radar image hides the base map's own place names. These sit to the right of each port, over land, to stay clear of ships at sea.
_PORT_LABELS_JS = """const PORT_LABELS = window.deck ? new deck.TextLayer({ id:"port-labels", data:__PORTS__, getPosition:d=>d.at, getText:d=>d.name, getSize:13, getColor:[240,239,236],
  fontFamily:"system-ui, sans-serif", getTextAnchor:"start", getPixelOffset:[12,0], background:true, getBackgroundColor:[13,13,13,200], backgroundPadding:[5,2] }) : null;""".replace(
    "__PORTS__", json.dumps([{"name": name, "at": [lon, lat]} for name, (lat, lon) in PORT_POSITIONS.items()])
)
MAP_PAGE_JS = f"{_SRCDOC_MAP_FIX_JS}\n{_PORT_LABELS_JS}"


def map_view(points: pd.DataFrame, fit_px: int = MAP_FIT_PX) -> pdk.ViewState:
    if points.empty:
        return pdk.ViewState(longitude=54.875, latitude=24.925, zoom=8)
    lon_span = points["lon"].max() - points["lon"].min()
    lat_span = points["lat"].max() - points["lat"].min()
    latitude = (points["lat"].max() + points["lat"].min()) / 2
    # Mercator stretches north-south distance by 1/cos(latitude).
    span = max(lon_span, lat_span / math.cos(math.radians(latitude)), 0.01)
    # deck.gl's world is 512px wide at zoom 0: fit the span inside the map height, with a margin.
    zoom = math.log2(fit_px * 360 / (512 * span))
    return pdk.ViewState(
        longitude=(points["lon"].max() + points["lon"].min()) / 2,
        latitude=latitude,
        zoom=min(max(zoom, 1), 11),
    )


def point_layer(points: pd.DataFrame, colour: list[int], radius: int, ring: int = 0, ring_colour: list[int] = RING_RGB) -> pdk.Layer:
    return pdk.Layer(
        "ScatterplotLayer",
        points,
        get_position=["lon", "lat"],
        get_fill_color=colour,
        get_line_color=ring_colour,
        get_radius=radius,
        # A plain string would be sent as a JS expression, not the literal unit.
        radius_units=pdk.types.String("pixels"),
        stroked=ring > 0,
        line_width_units=pdk.types.String("pixels"),
        get_line_width=ring,
        pickable=True,
    )


def circle_layer(centres: pd.DataFrame, radius_km: float, colour: list[int], fill_alpha: int = 30) -> pdk.Layer:
    return pdk.Layer(
        "ScatterplotLayer",
        centres,
        get_position=["lon", "lat"],
        get_radius=radius_km * 1000,
        get_fill_color=[*colour, fill_alpha],
        get_line_color=colour,
        stroked=True,
        line_width_units=pdk.types.String("pixels"),
        get_line_width=2,
    )


def radar_layer(image_uri: str, corners: list[list[float]], opacity: float = 0.9) -> pdk.Layer:
    return pdk.Layer("BitmapLayer", None, image=pdk.types.String(image_uri), bounds=corners, opacity=opacity)


def deck(layers: list[pdk.Layer], view: pdk.ViewState) -> pdk.Deck:
    return pdk.Deck(
        layers=layers,
        initial_view_state=view,
        map_style=pdk.map_styles.CARTO_DARK,
        tooltip={"html": "{tooltip}", "style": TOOLTIP_STYLE},
    )


def legend(items: list[tuple[str, str, bool]]) -> None:
    """A row of (colour, label, ringed) entries."""
    parts = []
    for colour, label, ringed in items:
        border = f"border:2px solid {INK};" if ringed else ""
        parts.append(
            f'<span style="display:inline-block;width:13px;height:13px;border-radius:50%;background:{colour};'
            f'{border}vertical-align:middle"></span> {label}'
        )
    st.markdown("&nbsp;&nbsp;&nbsp;".join(parts), unsafe_allow_html=True)


def style_figure(figure: go.Figure, height: int, y_title: str, legend_visible: bool = True) -> go.Figure:
    figure.update_layout(
        template="plotly_dark",
        paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE,
        height=height,
        margin={"l": 48, "r": 16, "t": 44 if legend_visible else 16, "b": 32},
        showlegend=legend_visible,
        legend={"orientation": "h", "y": 1.16, "x": 0, "font": {"color": INK_SECONDARY}},
        font={"color": INK_SECONDARY, "family": FONT},
    )
    figure.update_xaxes(type="category", showgrid=False, linecolor=AXIS, tickfont={"color": MUTED})
    figure.update_yaxes(
        title={"text": y_title, "font": {"color": MUTED, "size": 12}},
        gridcolor=GRID,
        zeroline=False,
        rangemode="tozero",
        tickfont={"color": MUTED},
    )
    return figure


def show_figure(figure: go.Figure) -> None:
    st.plotly_chart(figure, width="stretch", theme=None, config={"displaylogo": False})


@st.cache_data(show_spinner=False)
def cached_thumbnail(relative: object, directory: str) -> str | None:
    from pathlib import Path

    return thumbnail_uri(relative, directory=Path(directory))


@st.cache_data(show_spinner=False)
def cached_radar_image(relative: str) -> str | None:
    return radar_image_uri(relative)


def ship_type_label(value: object) -> str:
    """Fishing Watch's ship types, such as OTHER_NON_FISHING, in plain words."""
    if not isinstance(value, str) or not value or value == "INSUFFICIENT_DATA":
        return "Unknown"
    return value.replace("_", " ").capitalize()


def reported(values: pd.Series, missing: str = "Not reported") -> pd.Series:
    """Blank fields in plain words, rather than a table full of None."""
    return values.fillna("").replace("", missing)


def pass_time(moment: pd.Timestamp) -> str:
    return f"{moment:%d %b %H:%M} UTC"
