"""Seas of Data: a directory of real Sentinel-1 ship detections in the Gulf. Run with: streamlit run dashboard/app.py"""
import streamlit as st

import brand
from analysis import enrich, possible_dark
from components import pass_time
from data import (
    ContractError,
    attach_evidence,
    attach_gfw,
    contracts_dir,
    load_buoy_specs,
    load_detections,
    load_evidence,
    load_gfw_checks,
    load_gulf_metrics,
    load_manifest,
    load_ship_history,
    summarise,
)
from views import explorer, history, methods, movement, playback, ports, review, siting, tracker

ALL_PASSES = "All passes"

st.set_page_config(page_title="Seas of Data · Gulf dark-ship radar", page_icon="🛰️", layout="wide")
brand.apply_style()

try:
    detections = load_detections()
except ContractError as exc:
    st.error(f"Detections file rejected: {exc}")
    st.stop()

if detections.is_sample:
    st.warning("Sample data, not real results. The real file has not been published yet.", icon="⚠️")
if detections.frame.empty:
    st.info("This detections file has no detections yet.")
    st.stop()

directory = contracts_dir()
manifest = load_manifest()
gulf_metrics = load_gulf_metrics()
evidence, evidence_state = load_evidence(detections.path)
if evidence_state == "stale" and not detections.is_sample:
    st.warning("The radar images and second opinion were built from an older data release, so they're hidden. Run dashboard/pipeline to rebuild them.", icon="⚠️")

gfw_checks = load_gfw_checks(detections.path)
ship_history = load_ship_history()
frame = enrich(attach_gfw(attach_evidence(detections.frame, evidence), gfw_checks))
dark = possible_dark(frame)
brand.hero(
    passes=frame["scene_id"].nunique(),
    detections=len(frame),
    ships=int(frame["radar_class"].eq("ship").sum()),
    leads=int(dark.sum()),
    latest=pass_time(frame["timestamp"].max()),
    checked=bool(gfw_checks) or bool(dark.any()),
)
if gfw_checks:
    pending = [item for item in gfw_checks["passes"] if not item.get("available")]
    verb = "isn't" if len(pending) == 1 else "aren't"
    note = f" {len(pending)} of {len(gfw_checks['passes'])} passes {verb} published yet." if pending else ""
    st.info(
        "AIS checks come from Global Fishing Watch's own radar and AIS matching. "
        f"Possibly dark means a ship-class target with no AIS match, which is a reason to look closer but doesn't prove a ship switched AIS off.{note}",
        icon="ℹ️",
    )
elif not dark.any():
    st.info("These radar detections haven't been checked against AIS yet, so nothing here says a ship is dark. Each one is a real radar target.", icon="ℹ️")

passes = frame.groupby("scene_id").agg(time=("timestamp", "first"), detections=("id", "size")).sort_values("time")
total_passes = len(passes)
pass_options = {
    f"{row.time:%d %b %H:%M} UTC ({row.detections} detections)": scene for scene, row in passes.iloc[::-1].iterrows()
}
pass_options[f"{ALL_PASSES} ({len(frame)} detections)"] = None
choice = st.selectbox("Satellite pass", list(pass_options), key="pass_choice")
scene_id = pass_options[choice]
selected = frame if scene_id is None else frame[frame["scene_id"] == scene_id]

stats = summarise(selected)
total_tile, ship_tile, uncertain_tile, fixed_tile, ais_tile = st.columns(5)
total_tile.metric("Detections", f"{stats['total']:,}")
ship_tile.metric("Ship class", f"{stats['ship']:,}")
uncertain_tile.metric("Uncertain", f"{stats['uncertain']:,}")
fixed_tile.metric("Likely fixed", f"{stats['likely_fixed']:,}")
if selected["gfw_check"].eq("not_available").all():
    ais_tile.metric("AIS check", "Pending", help="Not published yet: Fishing Watch's radar and AIS matching runs about 5 days behind.")
elif dark.any():
    ais_tile.metric("Possibly dark", f"{int(possible_dark(selected).sum()):,}")
else:
    ais_tile.metric("AIS check", "Not yet")

if scene_id is None:
    st.caption(f"Across all {total_passes} passes, one ship can be counted several times. Pick a single pass for a count at one moment.")
else:
    row = selected.iloc[0]
    product = f" Product {row['product']}." if isinstance(row["product"], str) else ""
    st.caption(f"Sentinel-1 pass {pass_time(row['timestamp'])}, scene {scene_id}.{product}")

tracker_tab, explorer_tab, movement_tab, history_tab, playback_tab, port_tab, review_tab, siting_tab, methods_tab = st.tabs(
    [
        ":material/radar: Ship tracker",
        ":material/travel_explore: Explorer",
        ":material/route: Ship movement",
        ":material/history: Ship history",
        ":material/play_circle: Radar playback",
        ":material/anchor: Port watch",
        ":material/fact_check: Review queue",
        ":material/sensors: Buoy siting",
        ":material/menu_book: Methods and data",
    ]
)
with tracker_tab:
    tracker.render(frame)
with explorer_tab:
    explorer.render(selected, frame, evidence, scene_id, directory, manifest, total_passes, gfw_checks, ship_history)
with movement_tab:
    movement.render()
with history_tab:
    history.render(ship_history)
with playback_tab:
    playback.render(frame, evidence, manifest)
with port_tab:
    ports.render(frame)
with review_tab:
    review.render(frame, directory, gulf_metrics)
with siting_tab:
    siting.render(frame, load_buoy_specs())
with methods_tab:
    methods.render(frame, manifest, gulf_metrics, evidence, gfw_checks)

brand.footer()
