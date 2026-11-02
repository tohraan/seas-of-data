"""Seas of Data monitoring dashboard. Run with: uv run streamlit run app.py"""
import math

import pandas as pd
import plotly.graph_objects as go
import pydeck as pdk
import streamlit as st

from data import ContractError, load_detections, load_port_activity, summarise

DARK_VESSEL = [208, 59, 59]
AIS_VESSEL = [57, 135, 229]
RING = [240, 239, 236]
MAP_HEIGHT_PX = 460
MAP_FIT_PX = 360

# Validated categorical order for the dark surface. Assigned by sorted port name so a port keeps its colour.
PORT_COLOURS = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"]
METRICS = {
    "Activity index": "activity_index",
    "Vessel count": "vessel_count",
    "Berth occupancy (%)": "berth_occupancy_pct",
}


def map_view(points: pd.DataFrame) -> pdk.ViewState:
    if points.empty:
        return pdk.ViewState(longitude=0, latitude=20, zoom=1)
    lon_span = points["lon"].max() - points["lon"].min()
    lat_span = points["lat"].max() - points["lat"].min()
    latitude = (points["lat"].max() + points["lat"].min()) / 2
    # Mercator stretches north-south distance by 1/cos(latitude).
    span = max(lon_span, lat_span / math.cos(math.radians(latitude)), 0.01)
    # deck.gl's world is 512px wide at zoom 0: fit the span inside the map height, with a margin.
    zoom = math.log2(MAP_FIT_PX * 360 / (512 * span))
    return pdk.ViewState(
        longitude=(points["lon"].max() + points["lon"].min()) / 2,
        latitude=latitude,
        zoom=min(max(zoom, 1), 11),
    )


def vessel_layer(points: pd.DataFrame, colour: list[int], radius: int, ring: int) -> pdk.Layer:
    return pdk.Layer(
        "ScatterplotLayer",
        points,
        get_position=["lon", "lat"],
        get_fill_color=colour,
        get_line_color=RING,
        get_radius=radius,
        # A plain string would be sent as a JS expression, not the literal unit.
        radius_units=pdk.types.String("pixels"),
        stroked=ring > 0,
        line_width_units=pdk.types.String("pixels"),
        get_line_width=ring,
        pickable=True,
    )


def detection_labels(detections: pd.DataFrame) -> pd.DataFrame:
    labelled = detections.copy()
    labelled["status"] = labelled["dark"].map({True: "Dark vessel", False: "AIS matched"})
    labelled["confidence_label"] = labelled["confidence"].map("{:.0%}".format)
    labelled["length_label"] = labelled["length_m"].map(lambda v: "unknown" if pd.isna(v) else f"{v:.0f} m")
    labelled["mmsi_label"] = labelled["mmsi"].fillna("none")
    labelled["port_label"] = labelled["port"].fillna("open water")
    labelled["time_label"] = labelled["timestamp"].dt.strftime("%d %b %Y %H:%M UTC")
    # Only these reach the browser: the raw nullable columns would serialise as invalid JSON NaN.
    return labelled[[
        "id", "lon", "lat", "dark", "status", "confidence_label",
        "length_label", "mmsi_label", "port_label", "time_label",
    ]]


def render_map(detections: pd.DataFrame) -> None:
    labelled = detection_labels(detections)
    # Dark vessels draw last and larger, with a ring, so they read without relying on colour.
    layers = [
        vessel_layer(labelled[~labelled["dark"]], AIS_VESSEL, 6, 0),
        vessel_layer(labelled[labelled["dark"]], DARK_VESSEL, 9, 2),
    ]
    tooltip = {
        "html": (
            "<b>{status}</b> ({id})<br/>Confidence {confidence_label}<br/>Length {length_label}<br/>"
            "MMSI {mmsi_label}<br/>Port {port_label}<br/>{time_label}"
        ),
        "style": {"backgroundColor": "#1a1a19", "color": "#f0efec", "fontSize": "13px"},
    }
    st.pydeck_chart(
        pdk.Deck(layers=layers, initial_view_state=map_view(detections), map_style=pdk.map_styles.CARTO_DARK, tooltip=tooltip),
        height=MAP_HEIGHT_PX,
    )
    st.markdown(
        '<span style="display:inline-block;width:14px;height:14px;border-radius:50%;background:#d03b3b;'
        'border:2px solid #f0efec;vertical-align:middle"></span> Dark vessel (no AIS match)'
        '&nbsp;&nbsp;&nbsp;<span style="display:inline-block;width:12px;height:12px;border-radius:50%;'
        'background:#3987e5;vertical-align:middle"></span> AIS matched',
        unsafe_allow_html=True,
    )


def render_table(detections: pd.DataFrame) -> None:
    table = detections.sort_values(["dark", "confidence"], ascending=[False, False]).copy()
    table["status"] = table["dark"].map({True: "Dark vessel", False: "AIS matched"})
    st.dataframe(
        table[["id", "status", "confidence", "length_m", "mmsi", "port", "lat", "lon", "timestamp", "scene_id"]],
        hide_index=True,
        width="stretch",
        column_config={
            "id": "ID",
            "status": "Status",
            "confidence": st.column_config.ProgressColumn("Confidence", format="percent", min_value=0, max_value=1),
            "length_m": st.column_config.NumberColumn("Length (m)", format="%d"),
            "mmsi": "MMSI",
            "port": "Port",
            "lat": st.column_config.NumberColumn("Lat", format="%.3f"),
            "lon": st.column_config.NumberColumn("Lon", format="%.3f"),
            "timestamp": st.column_config.DatetimeColumn("Time (UTC)", format="DD MMM YYYY HH:mm"),
            "scene_id": "Scene",
        },
    )


def port_chart(activity: pd.DataFrame, label: str) -> go.Figure:
    column = METRICS[label]
    colours = dict(zip(sorted(activity["port"].unique()), PORT_COLOURS))
    figure = go.Figure()
    for port, colour in colours.items():
        rows = activity[activity["port"] == port]
        figure.add_trace(
            go.Scatter(
                x=rows["date"],
                y=rows[column],
                name=port,
                mode="lines+markers+text",
                line={"color": colour, "width": 2},
                marker={"color": colour, "size": 9, "line": {"color": "#1a1a19", "width": 2}},
                # Label only the latest point, in text ink rather than the series colour.
                text=[""] * (len(rows) - 1) + [port],
                textposition="middle right",
                textfont={"color": "#c3c2b7", "size": 12},
                cliponaxis=False,
                hovertemplate="%{y:,.1f}<extra>" + port + "</extra>",
            )
        )
    dates = sorted(activity["date"].unique())
    figure.update_layout(
        template="plotly_dark",
        paper_bgcolor="#1a1a19",
        plot_bgcolor="#1a1a19",
        height=460,
        margin={"l": 48, "r": 96, "t": 40, "b": 40},
        hovermode="x unified",
        legend={"orientation": "h", "y": 1.08, "x": 0, "font": {"color": "#c3c2b7"}},
        font={"color": "#c3c2b7", "family": "system-ui, -apple-system, Segoe UI, sans-serif"},
    )
    figure.update_xaxes(
        showgrid=False,
        linecolor="#383835",
        tickfont={"color": "#898781"},
        tickformat="%d %b",
        tickvals=dates if len(dates) <= 8 else None,
    )
    figure.update_yaxes(gridcolor="#2c2c2a", zeroline=False, tickfont={"color": "#898781"})
    return figure


def render_port_activity() -> None:
    st.subheader("Port activity")
    try:
        loaded = load_port_activity()
    except ContractError as exc:
        st.error(f"Port activity file rejected: {exc}")
        return
    if loaded.is_sample:
        st.warning("Sample data, not real results.", icon="⚠️")
    if loaded.frame.empty:
        st.info("No port activity in this file.")
        return

    label = st.selectbox("Metric", list(METRICS), label_visibility="collapsed")
    activity = loaded.frame
    busiest = activity.groupby("port")["vessel_count"].mean().nlargest(len(PORT_COLOURS)).index
    if activity["port"].nunique() > len(busiest):
        st.caption(f"Showing the {len(busiest)} busiest of {activity['port'].nunique()} ports.")
        activity = activity[activity["port"].isin(busiest)]
    st.plotly_chart(port_chart(activity, label), width="stretch", theme=None, config={"displaylogo": False})
    st.caption(f"Source: contracts/{loaded.path.name}")


st.set_page_config(page_title="Seas of Data", page_icon="🛰️", layout="wide")
st.title("Seas of Data: ship monitoring")

try:
    detections = load_detections()
except ContractError as exc:
    st.error(f"Detections file rejected: {exc}")
    detections = None

if detections is not None:
    if detections.is_sample:
        st.warning("Detections are sample data, not real results. The real file has not been published yet.", icon="⚠️")
    stats = summarise(detections.frame)
    total_tile, dark_tile, pct_tile = st.columns(3)
    total_tile.metric("Total ships", f"{stats['total']:,}")
    dark_tile.metric("Dark ships", f"{stats['dark']:,}")
    pct_tile.metric("Dark share", f"{stats['pct_dark']:.1f}%")

map_column, chart_column = st.columns([3, 2], gap="large")

if detections is not None:
    with map_column:
        st.subheader("Detections")
        dark_only = st.toggle("Dark vessels only")
        shown = detections.frame[detections.frame["dark"]] if dark_only else detections.frame
        render_map(shown)
        st.caption(f"Source: contracts/{detections.path.name}")

with chart_column:
    render_port_activity()

if detections is not None:
    st.subheader("Detections table")
    render_table(shown)
