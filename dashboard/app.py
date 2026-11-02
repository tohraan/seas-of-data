"""Seas of Data monitoring dashboard. Run with: uv run streamlit run app.py"""
import math

import pandas as pd
import plotly.graph_objects as go
import pydeck as pdk
import streamlit as st

from analysis import (
    PORT_POSITIONS,
    by_priority,
    enrich,
    health_checks,
    pass_summary,
    port_etas,
    reach_km,
    repeat_locations,
)
from data import (
    ContractError,
    ais_is_simulated,
    load_detections,
    load_port_activity,
    summarise,
)

DARK_VESSEL = [208, 59, 59]
AIS_VESSEL = [57, 135, 229]
RING = [240, 239, 236]
PORT_MARKER = [240, 239, 236]
MAP_HEIGHT_PX = 460
MAP_FIT_PX = 360
ALL_PASSES = "All passes"
PRIORITY_LABELS = {"High": "🔴 High", "Medium": "🟠 Medium", "Low": "🟡 Low", "Not flagged": "–"}
TOOLTIP_STYLE = {"backgroundColor": "#1a1a19", "color": "#f0efec", "fontSize": "13px"}

# Validated categorical order for the dark surface. Assigned by sorted name so a series keeps its colour.
SERIES_COLOURS = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"]


def status_labels(simulated: bool) -> dict[bool, str]:
    if simulated:
        return {True: "Dark (AIS simulated)", False: "Matched (AIS simulated)"}
    return {True: "Dark vessel", False: "AIS matched"}


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


def point_layer(points: pd.DataFrame, colour: list[int], radius: int, ring: int) -> pdk.Layer:
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


def map_points(detections: pd.DataFrame, simulated: bool) -> pd.DataFrame:
    labelled = detections.copy()
    status = labelled["dark"].map(status_labels(simulated))
    time = labelled["timestamp"].dt.strftime("%d %b %Y %H:%M UTC")
    lengths = labelled["length_m"].map(lambda v: "unknown length" if pd.isna(v) else f"{v:.0f} m")
    labelled["tooltip"] = [
        f"<b>{s}</b> ({i})<br/>{p} priority<br/>{loc}<br/>{length}, confidence {c:.2f}<br/>"
        f"Seen in {seen} pass(es) at this spot<br/>{a}<br/>{t}"
        for s, i, p, loc, length, c, seen, a, t in zip(
            status, labelled["id"], labelled["priority"], labelled["location"], lengths,
            labelled["confidence"], labelled["passes_seen"], labelled["ais_label"], time,
        )
    ]
    # Only these reach the browser: the raw nullable columns would serialise as invalid JSON NaN.
    return labelled[["lon", "lat", "dark", "tooltip"]]


def render_map(detections: pd.DataFrame, simulated: bool, density: bool) -> None:
    points = map_points(detections, simulated)
    # Dark vessels draw last and larger, with a ring, so they read without relying on colour.
    layers = [
        point_layer(points[~points["dark"]], AIS_VESSEL, 6, 0),
        point_layer(points[points["dark"]], DARK_VESSEL, 9, 2),
    ]
    if density:
        layers.insert(0, pdk.Layer("HeatmapLayer", points[["lon", "lat"]], get_position=["lon", "lat"], radius_pixels=45, opacity=0.55))
    st.pydeck_chart(
        pdk.Deck(
            layers=layers,
            initial_view_state=map_view(detections),
            map_style=pdk.map_styles.CARTO_DARK,
            tooltip={"html": "{tooltip}", "style": TOOLTIP_STYLE},
        ),
        height=MAP_HEIGHT_PX,
    )
    dark_label = "Dark vessel (no match to simulated AIS)" if simulated else "Dark vessel (no AIS match)"
    matched_label = "Matched to simulated AIS" if simulated else "AIS matched"
    st.markdown(
        '<span style="display:inline-block;width:14px;height:14px;border-radius:50%;background:#d03b3b;'
        f'border:2px solid #f0efec;vertical-align:middle"></span> {dark_label}'
        '&nbsp;&nbsp;&nbsp;<span style="display:inline-block;width:12px;height:12px;border-radius:50%;'
        f'background:#3987e5;vertical-align:middle"></span> {matched_label}',
        unsafe_allow_html=True,
    )


def detection_rows(frame: pd.DataFrame, total_passes: int) -> pd.DataFrame:
    rows = by_priority(frame).copy()
    rows["priority_label"] = rows["priority"].map(PRIORITY_LABELS)
    rows["status"] = rows["dark"].map({True: "🔴 Dark", False: "🔵 Matched"})
    rows["seen"] = [f"{seen} of {total_passes} passes" for seen in rows["passes_seen"]]
    return rows


def detection_columns(max_length: float) -> dict:
    return {
        "priority_label": "Priority",
        "id": "ID",
        "status": "Status",
        "reason": st.column_config.TextColumn("Why it's flagged", width="large"),
        "location": st.column_config.TextColumn("Location", width="large"),
        "size_class": "Size",
        "length_m": st.column_config.ProgressColumn("Length", format="%d m", min_value=0, max_value=max_length),
        "confidence": st.column_config.ProgressColumn("Radar score", format="%.2f", min_value=0, max_value=1),
        "seen": "Same spot seen in",
        "ais_label": st.column_config.TextColumn("AIS", width="medium"),
        "timestamp": st.column_config.DatetimeColumn("Pass (UTC)", format="DD MMM HH:mm"),
        "map_url": st.column_config.LinkColumn("Map", display_text="Open"),
    }


def download_button(frame: pd.DataFrame, file_name: str, key: str) -> None:
    columns = [
        "id", "priority", "reason", "dark", "ais_label", "confidence", "length_m", "size_class",
        "location", "passes_seen", "lat", "lon", "timestamp", "scene_id",
    ]
    st.download_button("Download CSV", by_priority(frame)[columns].to_csv(index=False), file_name, "text/csv", key=key)


def render_watchlist(frame: pd.DataFrame, total_passes: int) -> None:
    dark = frame[frame["dark"]]
    if dark.empty:
        st.info("No dark vessels in this selection.")
        return
    rows = detection_rows(dark, total_passes)
    for column, (_, row) in zip(st.columns(3), rows.head(3).iterrows()):
        with column.container(border=True):
            st.markdown(f"**{row['priority_label']} · {row['id']}**")
            st.markdown(row["location"])
            length = "Length unknown" if pd.isna(row["length_m"]) else f"{row['length_m']:.0f} m"
            st.markdown(f"{length} · radar score {row['confidence']:.2f}")
            st.caption(row["reason"])
            st.link_button("Open on map", row["map_url"])
    st.dataframe(
        rows,
        hide_index=True,
        width="stretch",
        column_order=["priority_label", "id", "map_url", "reason", "location", "length_m", "confidence", "seen", "timestamp"],
        column_config=detection_columns(float(frame["length_m"].max())),
    )
    st.caption(
        "High means a strong radar score (0.60 or more) and 50 m or longer. Medium means one of those, or inside a port area. "
        "A spot seen in 3 or more passes drops one level, because it may be anchored or a fixed structure. "
        "These thresholds are our own starting rules, not calibrated."
    )
    download_button(dark, "watchlist.csv", "watchlist_csv")


def render_detection_table(frame: pd.DataFrame, total_passes: int) -> None:
    show_column, zone_column, size_column, score_column, search_column = st.columns([1, 2, 2, 2, 2])
    show = show_column.selectbox("Show", ["All", "Dark only", "Matched only"], key="table_show")
    zones = zone_column.multiselect("Area", sorted(frame["zone"].unique()), key="table_zones", placeholder="All areas")
    sizes = size_column.multiselect("Size", ["Small", "Medium", "Large", "Unknown"], key="table_sizes", placeholder="All sizes")
    score = score_column.slider("Minimum radar score", 0.0, 1.0, 0.0, 0.05, key="table_score")
    search = search_column.text_input("Search ID or MMSI", key="table_search").strip()

    filtered = frame[frame["confidence"] >= score]
    if show != "All":
        filtered = filtered[filtered["dark"] == (show == "Dark only")]
    if zones:
        filtered = filtered[filtered["zone"].isin(zones)]
    if sizes:
        filtered = filtered[filtered["size_class"].isin(sizes)]
    if search:
        needle = search.lower()
        filtered = filtered[[needle in f"{i} {a}".lower() for i, a in zip(filtered["id"], filtered["ais_label"])]]

    st.caption(f"{len(filtered)} of {len(frame)} detections. Sorted by priority, then radar score.")
    st.dataframe(
        detection_rows(filtered, total_passes),
        hide_index=True,
        width="stretch",
        height=460,
        column_order=["priority_label", "id", "map_url", "status", "location", "size_class", "length_m", "confidence", "seen", "ais_label", "timestamp"],
        column_config=detection_columns(float(frame["length_m"].max())),
    )
    if not filtered.empty:
        download_button(filtered, "detections.csv", "detections_csv")


def render_reach(frame: pd.DataFrame) -> None:
    dark = by_priority(frame[frame["dark"]])
    if dark.empty:
        st.info("No dark vessels in this selection.")
        return
    st.markdown(
        "A dark vessel has no heading or speed to project from, so this shows the area it could have reached, not where it is. "
        "Choose how fast it might be going and how far ahead to look."
    )
    options = {f"{row.id}: {row.priority} priority, {row.location}": row for row in dark.itertuples()}
    choice_column, speed_column, hours_column = st.columns([3, 1, 1])
    choice = choice_column.selectbox("Dark vessel", list(options), key="reach_choice")
    speed = speed_column.slider("Assumed speed (knots)", 1, 30, 12, key="reach_speed")
    hours = hours_column.slider("Hours after it was seen", 1, 72, 6, key="reach_hours")

    vessel = options[choice]
    radius = reach_km(speed, hours)
    elapsed = (pd.Timestamp.now(tz="UTC") - vessel.timestamp).total_seconds() / 3600
    etas = port_etas(vessel.lat, vessel.lon, speed)
    etas["within"] = etas["hours"].map(lambda value: "Yes" if value <= hours else "No")

    map_column, detail_column = st.columns([3, 2], gap="large")
    with map_column:
        lat_margin = radius / 111
        lon_margin = lat_margin / math.cos(math.radians(vessel.lat))
        bounds = pd.DataFrame({
            "lat": [vessel.lat - lat_margin, vessel.lat + lat_margin],
            "lon": [vessel.lon - lon_margin, vessel.lon + lon_margin],
        })
        ports = pd.DataFrame([
            {"lat": lat, "lon": lon, "tooltip": f"<b>{name}</b>"} for name, (lat, lon) in PORT_POSITIONS.items()
        ])
        layers = [
            pdk.Layer(
                "ScatterplotLayer",
                pd.DataFrame([{"lat": vessel.lat, "lon": vessel.lon}]),
                get_position=["lon", "lat"],
                get_radius=radius * 1000,
                get_fill_color=[*DARK_VESSEL, 45],
                get_line_color=DARK_VESSEL,
                stroked=True,
                line_width_units=pdk.types.String("pixels"),
                get_line_width=2,
            ),
            point_layer(ports, PORT_MARKER, 6, 0),
            point_layer(pd.DataFrame([{"lat": vessel.lat, "lon": vessel.lon, "tooltip": f"<b>{vessel.id}</b> last seen here"}]), DARK_VESSEL, 8, 2),
        ]
        st.pydeck_chart(
            pdk.Deck(
                layers=layers,
                initial_view_state=map_view(bounds),
                map_style=pdk.map_styles.CARTO_DARK,
                tooltip={"html": "{tooltip}", "style": TOOLTIP_STYLE},
            ),
            height=MAP_HEIGHT_PX,
        )
    with detail_column:
        st.metric(f"After {hours} h, it could be up to", f"{radius:,.0f} km away")
        st.metric("Last seen", f"{elapsed:,.0f} hours ago", help="Time since this satellite pass, compared with the clock now.")
        st.markdown(f"**Time to reach each port at {speed} knots**")
        st.dataframe(
            etas,
            hide_index=True,
            width="stretch",
            column_config={
                "port": "Port",
                "km": st.column_config.NumberColumn("Distance (km)", format="%.0f"),
                "hours": st.column_config.NumberColumn("Hours", format="%.1f"),
                "within": f"Within {hours} h?",
            },
        )
        st.caption("Straight-line distance, ignoring land, currents and traffic. The white dots are ports.")


def stacked_bars(frame: pd.DataFrame, series: str, y_title: str) -> go.Figure:
    frame = frame.assign(pass_label=frame["timestamp"].dt.strftime("%d %b %H:%M"))
    order = frame.sort_values("timestamp")["pass_label"].unique()
    counts = frame.groupby(["pass_label", series]).size().unstack(fill_value=0).reindex(order)
    figure = go.Figure()
    for name, colour in zip(sorted(counts.columns), SERIES_COLOURS):
        figure.add_trace(
            go.Bar(
                x=counts.index,
                y=counts[name],
                name=name,
                marker={"color": colour, "line": {"color": "#1a1a19", "width": 2}},
                hovertemplate="%{y} detections<extra>" + name + "</extra>",
            )
        )
    figure.update_layout(
        template="plotly_dark",
        paper_bgcolor="#1a1a19",
        plot_bgcolor="#1a1a19",
        height=320,
        margin={"l": 48, "r": 16, "t": 44, "b": 32},
        barmode="stack",
        bargap=0.35,
        legend={"orientation": "h", "y": 1.16, "x": 0, "font": {"color": "#c3c2b7"}},
        font={"color": "#c3c2b7", "family": "system-ui, -apple-system, Segoe UI, sans-serif"},
    )
    figure.update_xaxes(type="category", showgrid=False, linecolor="#383835", tickfont={"color": "#898781"})
    figure.update_yaxes(
        title={"text": y_title, "font": {"color": "#898781", "size": 12}},
        gridcolor="#2c2c2a",
        zeroline=False,
        tickfont={"color": "#898781"},
    )
    return figure


def render_patterns(frame: pd.DataFrame) -> None:
    area_column, size_column = st.columns(2, gap="large")
    with area_column:
        st.subheader("Detections per pass, by area")
        st.plotly_chart(stacked_bars(frame, "zone", "Detections"), width="stretch", theme=None, config={"displaylogo": False})
    with size_column:
        st.subheader("Detections per pass, by size")
        st.plotly_chart(stacked_bars(frame, "size_class", "Detections"), width="stretch", theme=None, config={"displaylogo": False})

    st.subheader("Spots seen in more than one pass")
    repeats = repeat_locations(frame)
    if repeats.empty:
        st.info("No spot appears in more than one pass.")
        return
    st.markdown(
        f"**{len(repeats)} spots** were seen in two or more passes. They could be anchored ships, or fixed structures that "
        "shouldn't count as ships at all. A spot that is sometimes dark can't be read as a ship switching AIS off "
        "while the AIS is simulated. With real AIS, it would be one of the strongest signals here."
    )
    st.dataframe(
        repeats,
        hide_index=True,
        width="stretch",
        column_config={
            "passes": st.column_config.NumberColumn("Passes seen", format="%d"),
            "detections": st.column_config.NumberColumn("Detections", format="%d"),
            "times_dark": st.column_config.NumberColumn("Times dark", format="%d"),
            "shortest_m": st.column_config.NumberColumn("Shortest (m)", format="%d"),
            "longest_m": st.column_config.NumberColumn("Longest (m)", format="%d"),
            "lat": st.column_config.NumberColumn("Lat", format="%.4f"),
            "lon": st.column_config.NumberColumn("Lon", format="%.4f"),
            "location": st.column_config.TextColumn("Location", width="large"),
        },
    )
    st.caption("Sightings within 300 m count as the same spot, which is our assumption for how far an anchored ship swings.")


def port_chart(activity: pd.DataFrame) -> go.Figure:
    # Bars per pass, not lines: counts are too small for the passes to read as a trend.
    colours = dict(zip(sorted(activity["port"].unique()), SERIES_COLOURS))
    figure = go.Figure()
    for port, colour in colours.items():
        rows = activity[activity["port"] == port]
        figure.add_trace(
            go.Bar(
                x=rows["date"].dt.strftime("%d %b"),
                y=rows["vessel_count"],
                name=port,
                marker={"color": colour, "cornerradius": 4},
                text=rows["vessel_count"],
                textposition="outside",
                textfont={"color": "#c3c2b7", "size": 12},
                cliponaxis=False,
                customdata=rows["activity_index"],
                hovertemplate="%{y} vessels<br>Activity index %{customdata:.1f}<extra>" + port + "</extra>",
            )
        )
    figure.update_layout(
        template="plotly_dark",
        paper_bgcolor="#1a1a19",
        plot_bgcolor="#1a1a19",
        height=300,
        margin={"l": 40, "r": 16, "t": 44, "b": 32},
        barmode="group",
        bargap=0.3,
        bargroupgap=0.05,
        legend={"orientation": "h", "y": 1.16, "x": 0, "font": {"color": "#c3c2b7"}},
        font={"color": "#c3c2b7", "family": "system-ui, -apple-system, Segoe UI, sans-serif"},
    )
    figure.update_xaxes(
        type="category",
        categoryorder="array",
        categoryarray=activity.sort_values("date")["date"].dt.strftime("%d %b").unique(),
        showgrid=False,
        linecolor="#383835",
        tickfont={"color": "#898781"},
    )
    figure.update_yaxes(
        title={"text": "Vessels per pass", "font": {"color": "#898781", "size": 12}},
        gridcolor="#2c2c2a",
        zeroline=False,
        tickfont={"color": "#898781"},
    )
    return figure


def render_port_table(activity: pd.DataFrame) -> None:
    st.dataframe(
        activity.sort_values(["date", "port"]),
        hide_index=True,
        width="stretch",
        column_order=["date", "port", "vessel_count", "activity_index", "berth_occupancy_pct"],
        column_config={
            "date": st.column_config.DateColumn("Pass", format="DD MMM"),
            "port": "Port",
            "vessel_count": st.column_config.NumberColumn("Vessels", format="%d"),
            "activity_index": st.column_config.NumberColumn("Activity index", format="%.1f"),
            "berth_occupancy_pct": st.column_config.NumberColumn("Berths (%)", format="%.1f"),
        },
    )


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

    activity = loaded.frame
    busiest = activity.groupby("port")["vessel_count"].mean().nlargest(len(SERIES_COLOURS)).index
    if activity["port"].nunique() > len(busiest):
        st.caption(f"Showing the {len(busiest)} busiest of {activity['port'].nunique()} ports.")
        activity = activity[activity["port"].isin(busiest)]
    st.plotly_chart(port_chart(activity), width="stretch", theme=None, config={"displaylogo": False})
    render_port_table(activity)
    low, high = activity["vessel_count"].min(), activity["vessel_count"].max()
    st.caption(
        f"Counts are small ({low}-{high} vessels per pass), so changes in the activity index "
        f"between passes are not a trend. The index compares each pass with that port's own median, and berth % uses "
        f"assumed port capacities. Source: contracts/{loaded.path.name}"
    )


st.set_page_config(page_title="Seas of Data", page_icon="🛰️", layout="wide")
st.title("Seas of Data: ship monitoring")

try:
    detections = load_detections()
except ContractError as exc:
    st.error(f"Detections file rejected: {exc}")
    detections = None

if detections is None:
    render_port_activity()
    st.stop()

if detections.is_sample:
    st.warning("Detections are sample data, not real results. The real file has not been published yet.", icon="⚠️")
if detections.frame.empty:
    st.info("This detections file has no detections yet.")
    render_port_activity()
    st.stop()

simulated = ais_is_simulated(detections.frame)
if simulated:
    st.info(
        "AIS is simulated. The dark ship count and share come from a simulation parameter, so they are not a finding.",
        icon="ℹ️",
    )

# Repeat sightings are worked out across every pass, before the pass filter narrows the view.
enriched = enrich(detections.frame)
passes = pass_summary(enriched)
total_passes = len(passes)
pass_options = {
    f"{row.time:%d %b %H:%M} UTC ({row.detections} detections)": row.scene_id
    for row in passes.iloc[::-1].itertuples()
}
pass_options[f"{ALL_PASSES} ({len(enriched)} detections)"] = None
pass_choice = st.selectbox("Satellite pass", list(pass_options), key="pass_choice")
scene = pass_options[pass_choice]
selected = enriched if scene is None else enriched[enriched["scene_id"] == scene]

suffix = " (AIS simulated)" if simulated else ""
stats = summarise(selected)
total_tile, dark_tile, pct_tile, priority_tile = st.columns(4)
total_tile.metric("Detections", f"{stats['total']:,}")
dark_tile.metric(f"Dark{suffix}", f"{stats['dark']:,}")
pct_tile.metric(f"Dark share{suffix}", f"{stats['pct_dark']:.1f}%")
priority_tile.metric("High priority", f"{(selected['priority'] == 'High').sum():,}")
if scene is None:
    st.caption("Across all passes, one ship can be counted several times. Pick a single pass for a ship count at one moment.")

map_tab, watchlist_tab, table_tab, reach_tab, patterns_tab, health_tab = st.tabs(
    ["Map", "Watchlist", "All detections", "Where could it be?", "Patterns", "Data health"]
)

with map_tab:
    map_column, chart_column = st.columns([3, 2], gap="large")
    with map_column:
        st.subheader("Detections")
        dark_toggle, density_toggle = st.columns(2)
        dark_only = dark_toggle.toggle("Dark vessels only", key="dark_only")
        density = density_toggle.toggle("Show busy areas", key="density")
        render_map(selected[selected["dark"]] if dark_only else selected, simulated, density)
        st.caption(f"Source: contracts/{detections.path.name}")
    with chart_column:
        render_port_activity()

with watchlist_tab:
    render_watchlist(selected, total_passes)

with table_tab:
    render_detection_table(selected, total_passes)

with reach_tab:
    render_reach(selected)

with patterns_tab:
    render_patterns(enriched)

with health_tab:
    st.markdown("What this data can and can't support. This covers all passes, whichever one is selected above.")
    st.dataframe(
        health_checks(enriched, pd.Timestamp.now(tz="UTC")),
        hide_index=True,
        width="stretch",
        column_config={
            "Result": st.column_config.TextColumn(width="medium"),
            "Why it matters": st.column_config.TextColumn(width="large"),
        },
    )
