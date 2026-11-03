"""Live ships: real AIS positions that update as new reports arrive. With no feed, it says so and shows nothing."""
from pathlib import Path

import pandas as pd
import pydeck as pdk
import streamlit as st

from components import (
    FIXED_RGB,
    MAP_HEIGHT_PX,
    MUTED,
    SHIP_HEX,
    SHIP_RGB,
    UNCERTAIN_RGB,
    circle_layer,
    deck,
    legend,
    point_layer,
    reported,
)
from data import derived_dir
from live_ais import (
    ESTIMATE_LIMIT_S,
    FEED_STALE_S,
    SILENT_AFTER_S,
    ais_dir,
    feed_summary,
    key_present,
    last_write_age,
    read_reports,
    ship_states,
    water_lookup,
)

REFRESH_S = 5
RING_KEY = "live_rings"
LIVE_COLUMNS = ["name", "mmsi", "status", "sog", "cog", "heard", "estimated"]
# The box that ml/ais/capture.py listens to.
VIEW = pdk.ViewState(longitude=54.9, latitude=24.95, zoom=8.2)
CAPTURE_COMMAND = (
    "cd ml\n"
    "uv run --no-project --python 3.12 --with websockets --with python-dotenv python -m ais.capture --hours 48"
)


def describe_age(seconds: float) -> str:
    if seconds < 90:
        return f"{seconds:.0f} s ago"
    if seconds < 5400:
        return f"{seconds / 60:.0f} min ago"
    return f"{seconds / 3600:.1f} h ago"


def show_no_reports(now: float) -> None:
    """Nothing heard in the last hour. Reports can stop because the feed is quiet, not only because nothing is connected."""
    last_write = last_write_age(ais_dir(), now)
    if last_write is not None:
        st.info(
            f"No ships heard here in the last hour. The last report came in {describe_age(last_write)}. The free AIS feed has very few receivers "
            "on this coast, so quiet hours are normal. This page can't tell that apart from a stopped collector, so if it stays quiet for hours, restart it:",
            icon="📡",
        )
        st.code(CAPTURE_COMMAND, language="bash")
    elif key_present():
        st.info("The live AIS key is saved, but nothing is collecting reports yet. Start the collector and leave it running:", icon="📡")
        st.code(CAPTURE_COMMAND, language="bash")
    else:
        st.info(
            "No live data is connected, so no ships are shown here. Radar can't give live positions: it's a snapshot every few days, "
            "with no speed or heading. Live positions need AIS, so add a free key from aisstream.io to `ml/.env` as `AISSTREAM_KEY=...`.",
            icon="📡",
        )
    st.caption("Global Fishing Watch can't drive this live view, because its AIS data runs about 3-5 days behind.")


def tooltip(row: pd.Series) -> str:
    name = row["name"] if isinstance(row["name"], str) else "Name not reported"
    speed = "speed unknown" if pd.isna(row["sog"]) else f"{row['sog']:.1f} knots"
    course = "" if pd.isna(row["cog"]) else f", heading {row['cog']:.0f}°"
    position = "Estimated from its last report" if row["estimated"] else "Last reported position"
    return f"<b>{name}</b><br/>MMSI {row['mmsi']}<br/>{row['status']}: {speed}{course}<br/>Heard {describe_age(row['age_s'])}<br/>{position}"


@st.cache_resource(show_spinner=False)
def water_check(path: str):
    return water_lookup(Path(path))


def choose_rings(states: pd.DataFrame) -> set[str]:
    """Which quiet ships get a reach ring. None do until asked for, so the map stays readable."""
    quiet = states[states["reach_km"].notna()]
    if quiet.empty:
        return set()
    labels = {f"{row['name'] if isinstance(row['name'], str) else 'Name not reported'} ({row['mmsi']})": row["mmsi"] for _, row in quiet.iterrows()}
    # A ship leaves this list when it's heard again.
    if RING_KEY in st.session_state:
        st.session_state[RING_KEY] = [label for label in st.session_state[RING_KEY] if label in labels]
    chosen = st.multiselect("Show how far a quiet ship could have gone", list(labels), key=RING_KEY, placeholder="Pick a ship")
    return {labels[label] for label in chosen}


def live_layers(states: pd.DataFrame, ring_ships: set[str]) -> list[pdk.Layer]:
    points = states.assign(tooltip=[tooltip(row) for _, row in states.iterrows()])
    plain = points[["mmsi", "lat", "lon", "status", "tooltip"]]
    tracks = points.loc[points["track"].notna(), ["track", "status"]]
    layers: list[pdk.Layer] = []
    if not tracks.empty:
        layers.append(pdk.Layer(
            "PathLayer",
            tracks,
            get_path="track",
            get_color=[*SHIP_RGB, 110],
            get_width=2,
            width_units=pdk.types.String("pixels"),
        ))
    quiet = points[points["reach_km"].notna() & points["mmsi"].isin(ring_ships)]
    for _, row in quiet.iterrows():
        layers.append(circle_layer(pd.DataFrame([{"lat": row["reported_lat"], "lon": row["reported_lon"]}]), row["reach_km"], FIXED_RGB, 12))
    layers += [
        point_layer(plain[plain["status"] == "Stopped"], UNCERTAIN_RGB, 4),
        point_layer(plain[plain["status"] == "Moving"], SHIP_RGB, 6),
        point_layer(plain[plain["status"] == "Not heard"], FIXED_RGB, 6, 2),
    ]
    return layers


def show_feed() -> None:
    now = pd.Timestamp.now(tz="UTC").timestamp()
    reports = read_reports(ais_dir(), now)
    if reports.empty:
        show_no_reports(now)
        return
    states = ship_states(reports, now, water_check(str(derived_dir() / "water_mask.npz")))
    summary = feed_summary(states, reports, now)
    if summary["newest_age_s"] > FEED_STALE_S:
        st.warning(f"The newest AIS report is {describe_age(summary['newest_age_s'])}, so the collector may have stopped. These positions are out of date.", icon="⚠️")

    ship_tile, moving_tile, stopped_tile, quiet_tile, newest_tile = st.columns(5)
    ship_tile.metric("Ships in the last hour", f"{summary['ships']:,}")
    moving_tile.metric("Moving", f"{summary['moving']:,}")
    stopped_tile.metric("Stopped", f"{summary['stopped']:,}")
    quiet_tile.metric("Not heard lately", f"{summary['not_heard']:,}", help=f"No report for over {SILENT_AFTER_S // 60} minutes.")
    newest_tile.metric("Newest report", describe_age(summary["newest_age_s"]))

    ring_ships = choose_rings(states)
    st.pydeck_chart(deck(live_layers(states, ring_ships), VIEW), height=MAP_HEIGHT_PX, key="live_map")
    legend([(SHIP_HEX, "Moving", False), (MUTED, "Stopped", False), ("#c98500", "Not heard lately", True)])
    st.caption(
        f"Real AIS reports. Between reports, a moving ship's position is estimated from its last speed and course, for up to {ESTIMATE_LIMIT_S // 60} minutes. "
        f"A ship that goes quiet may just be out of range of the shore receivers, so that alone doesn't mean it switched its AIS off. "
        f"The free feed has very few receivers on this coast, so this shows only a small share of the ships really here. Base map: OpenStreetMap, CARTO."
    )
    table = states.sort_values(["status", "age_s"])
    table = table.assign(heard=table["age_s"].map(describe_age), name=reported(table["name"], "Name not reported"))
    st.dataframe(
        # A styler, because a blank number otherwise shows as "None".
        table[LIVE_COLUMNS].style.format({"sog": "{:.1f}", "cog": "{:.0f}"}, na_rep="–"),
        hide_index=True,
        width="stretch",
        height=320,
        column_order=LIVE_COLUMNS,
        column_config={
            "name": st.column_config.TextColumn("Name", width="medium"),
            "mmsi": "MMSI",
            "status": "Status",
            "sog": "Speed (knots)",
            "cog": "Course (°)",
            "heard": "Last heard",
            "estimated": st.column_config.CheckboxColumn("Position estimated"),
        },
    )


@st.fragment(run_every=REFRESH_S)
def live_panel() -> None:
    show_feed()


def render() -> None:
    now = pd.Timestamp.now(tz="UTC").timestamp()
    # Without a key no report can arrive, so there's nothing to keep checking for.
    if not key_present() and read_reports(ais_dir(), now).empty:
        show_no_reports(now)
    else:
        live_panel()
