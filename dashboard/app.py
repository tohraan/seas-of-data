"""Seas of Data: a directory of real Sentinel-1 ship detections in the Gulf. Run with: streamlit run dashboard/app.py"""
import streamlit as st

from analysis import enrich, possible_dark
from components import pass_time
from data import (
    ContractError,
    attach_evidence,
    contracts_dir,
    load_buoy_specs,
    load_detections,
    load_evidence,
    load_gulf_metrics,
    load_manifest,
    summarise,
)
from views import explorer, live, methods, playback, ports, review, siting

ALL_PASSES = "All passes"

st.set_page_config(page_title="Seas of Data", page_icon="🛰️", layout="wide")
st.title("Seas of Data: Gulf ship radar directory")

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

frame = enrich(attach_evidence(detections.frame, evidence))
dark = possible_dark(frame)
if not dark.any():
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
if dark.any():
    ais_tile.metric("Possibly dark", f"{int(possible_dark(selected).sum()):,}")
else:
    ais_tile.metric("AIS check", "Not yet")

if scene_id is None:
    st.caption(f"Across all {total_passes} passes, one ship can be counted several times. Pick a single pass for a count at one moment.")
else:
    row = selected.iloc[0]
    product = f" Product {row['product']}." if isinstance(row["product"], str) else ""
    st.caption(f"Sentinel-1 pass {pass_time(row['timestamp'])}, scene {scene_id}.{product}")

explorer_tab, live_tab, playback_tab, port_tab, review_tab, siting_tab, methods_tab = st.tabs(
    ["Explorer", "Live ships", "Playback", "Port watch", "Review queue", "Buoy siting", "Methods and data"]
)
with explorer_tab:
    explorer.render(selected, frame, evidence, scene_id, directory, manifest, total_passes)
with live_tab:
    live.render()
with playback_tab:
    playback.render(frame, evidence, manifest)
with port_tab:
    ports.render(frame)
with review_tab:
    review.render(frame, directory, gulf_metrics)
with siting_tab:
    siting.render(frame, load_buoy_specs())
with methods_tab:
    methods.render(frame, manifest, gulf_metrics, evidence)
