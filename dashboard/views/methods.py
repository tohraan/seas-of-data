"""Methods and data, for judges and researchers: where every number comes from, how good it is, and how to rebuild it."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from components import (
    GFW_ATTRIBUTION,
    INK_SECONDARY,
    SERIES_COLOURS,
    pass_time,
    show_figure,
    style_figure,
)
from data import Evidence, load_model_metrics

STAGE_LABELS = {
    "blobs_above_threshold": "Bright blobs found",
    "after_size_filter": "After size filter",
    "after_sea_mask": "After sea mask",
    "after_merge": "After merging",
}


def percent(value: float) -> str:
    return f"{value * 100:.0f}%"


def interval(block: dict) -> str:
    low, high = block["ci95"]
    return f"95% interval {percent(low)}-{percent(high)}"


def render_provenance(manifest: dict) -> None:
    st.subheader("Where the data comes from")
    real_column, not_column = st.columns(2)
    real_column.success(manifest.get("what_is_real", ""), icon="✅")
    not_column.warning(manifest.get("what_is_not", ""), icon="⚠️")
    rows = []
    for scene in manifest.get("scenes", []):
        detections = scene.get("detections", {})
        classes = detections.get("by_radar_class", {})
        rows.append({
            "Pass (UTC)": pd.Timestamp(scene["acquired_start_utc"]).strftime("%d %b %Y %H:%M"),
            "Satellite": scene.get("satellite"),
            "Detections": detections.get("n"),
            "Ship-class": classes.get("ship"),
            "Product": scene.get("product"),
            "SHA-256 (start)": (scene.get("sha256") or "")[:16],
            "Copernicus record": scene.get("copernicus_data_space", {}).get("url"),
        })
    st.dataframe(
        pd.DataFrame(rows),
        hide_index=True,
        width="stretch",
        column_config={
            "Product": st.column_config.TextColumn(width="large"),
            "Copernicus record": st.column_config.LinkColumn(display_text="Open"),
        },
    )
    area = manifest.get("area_searched", {})
    if area:
        st.caption(f"Area searched: {area.get('lon_min')}-{area.get('lon_max')} E, {area.get('lat_min')}-{area.get('lat_max')} N. The scenes themselves are wider. {manifest.get('attribution', '')}")


def render_funnel(manifest: dict) -> None:
    totals: dict[str, int] = {}
    for scene in manifest.get("scenes", []):
        for stage, count in scene.get("cfar", {}).get("stages", {}).items():
            totals[stage] = totals.get(stage, 0) + count
    if not totals:
        return
    st.subheader("From radar image to detection")
    labels = [STAGE_LABELS.get(stage, stage) for stage in totals]
    values = list(totals.values())
    figure = go.Figure(go.Bar(
        x=values, y=labels, orientation="h", text=values, textposition="outside", cliponaxis=False,
        marker={"color": SERIES_COLOURS[0], "cornerradius": 4}, textfont={"color": INK_SECONDARY},
        hovertemplate="%{y}: %{x}<extra></extra>",
    ))
    style_figure(figure, 240, "", legend_visible=False)
    figure.update_xaxes(type="linear", showgrid=False, showticklabels=False, zeroline=False, linecolor="#1a1a19")
    figure.update_yaxes(type="category", autorange="reversed", gridcolor="#1a1a19", title=None, tickfont={"color": INK_SECONDARY})
    figure.update_layout(margin={"l": 150, "r": 40, "t": 8, "b": 8})
    show_figure(figure)
    st.caption("Totals across all passes, for the CFAR detector. The review and class rule below then sort these into ship, uncertain and likely fixed.")


def render_precision(metrics: dict) -> None:
    st.subheader("How good are the detections?")
    classes = metrics.get("by_radar_class", {})
    whole = metrics.get("precision_strict_unsure_counts_as_not_ship")
    ship = classes.get("ship", {}).get("precision_strict")
    uncertain = classes.get("uncertain", {}).get("precision_strict")
    tiles = st.columns(3)
    if ship:
        tiles[0].metric("Ship class looks like a ship", percent(ship["estimate"]), help=interval(ship))
        tiles[0].caption(interval(ship))
    if uncertain:
        tiles[1].metric("Uncertain class looks like a ship", percent(uncertain["estimate"]), help=interval(uncertain))
        tiles[1].caption(interval(uncertain))
    if whole:
        tiles[2].metric("All detections look like a ship", percent(whole["estimate"]), help=interval(whole))
        tiles[2].caption(interval(whole))
    st.warning(
        f"{metrics.get('not', '')} Sample: {metrics.get('sample', {}).get('n', '?')} chips. Unsure chips count as not ships in these figures.",
        icon="⚠️",
    )
    bands = metrics.get("by_size_band", {})
    if bands:
        order = ["tiny", "small", "medium", "large+"]
        rows = [
            {
                "Size band": {"large+": "Large and very large"}.get(name, name.capitalize()),
                "Reviewed": bands[name]["n"],
                "Look like ships": bands[name]["confirmed"],
                "Share": percent(bands[name]["raw_share"]),
                "95% interval": f"{percent(bands[name]['wilson95'][0])}-{percent(bands[name]['wilson95'][1])}",
            }
            for name in order if name in bands
        ]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        st.caption("The smaller the target, the less often it looks like a ship.")


def render_fishing_watch_check(frame: pd.DataFrame, checks: dict | None) -> None:
    """How our detections line up with Fishing Watch's own processing of the same radar passes."""
    if not checks:
        return
    available = [item for item in checks.get("passes", []) if item.get("available")]
    if not available:
        return
    st.subheader("Checked against Global Fishing Watch")
    theirs = sum(item["gfw_total"] for item in available)
    paired = sum(item["paired"] for item in available)
    st.markdown(
        f"Fishing Watch runs its own ship detection on the same Sentinel-1 passes and matches the results to AIS. That gives us an outside check, on {len(available)} of {len(checks['passes'])} passes so far. "
        f"**Of their {theirs} targets, our detector also found {paired}.** The rest are ships we missed or targets near the coast that our sea mask excludes."
    )
    rows = []
    checked = frame[frame["gfw_check"].isin(["ais_match", "no_ais", "no_detection"])]
    for radar_class, label in [("ship", "Ship"), ("uncertain", "Uncertain"), ("likely_fixed", "Likely fixed")]:
        group = checked[checked["radar_class"] == radar_class]
        if group.empty:
            continue
        seen = group["gfw_check"].isin(["ais_match", "no_ais"])
        rows.append({
            "Our radar class": label,
            "Detections": len(group),
            "Also found by Fishing Watch": f"{int(seen.sum())} ({seen.mean() * 100:.0f}%)",
            "Matched to a ship's AIS": int((group["gfw_check"] == "ais_match").sum()),
            "No AIS match": int((group["gfw_check"] == "no_ais").sum()),
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption(
        "Positions are paired within 1 km, because Fishing Watch rounds them to about 1 km. "
        "That the ship class is found far more often than the uncertain class is independent support for the class rule. "
        "A target with no AIS match isn't proof of wrongdoing: its AIS may have been out of reception, or it may not be a ship."
    )
    pending = [item["scene_id"] for item in checks["passes"] if not item.get("available")]
    if pending:
        st.caption(f"Not published yet, because this data runs about 5 days behind: {', '.join(pending)}.")
    st.markdown(GFW_ATTRIBUTION)


def render_review_check(frame: pd.DataFrame) -> None:
    """Do the two independent signals agree with the visual review? Neither was used to make it."""
    reviewed = frame[frame["review"].isin(["confirmed", "unsure", "rejected"]) & frame["detector_check"].notna()]
    if reviewed.empty:
        return
    rows = []
    for verdict, label in [("confirmed", "Looks like a ship"), ("unsure", "Unsure"), ("rejected", "Not a ship")]:
        group = reviewed[reviewed["review"] == verdict]
        if group.empty:
            continue
        rows.append({
            "Visual review": label,
            "Chips": len(group),
            "YOLO also found": f"{int((group['detector_check'] == 'both').sum())} of {len(group)}",
            "Bright in VH": f"{int(group['vh_confirmed'].eq(True).sum())} of {len(group)}",
        })
    st.markdown("**A check on the visual review.** YOLO and the VH channel weren't used in the review, so they can test it.")
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption("Small samples, and the review itself isn't ground truth, but all three point the same way.")


def render_second_opinion(frame: pd.DataFrame, evidence: Evidence | None) -> None:
    st.subheader("Second opinion: the trained YOLO model and the VH channel")
    metrics = load_model_metrics()
    if evidence is None:
        st.info("The second-opinion files haven't been built for this version of the data. Run dashboard/pipeline to create them.")
        return
    passes = evidence.passes
    cfar = sum(item["cfar"] for item in passes)
    yolo = sum(item["yolo"] for item in passes)
    both = sum(item["both"] for item in passes)
    vh = sum(item["vh_confirmed"] for item in passes)
    targets = evidence.targets
    measured = len(targets)
    threshold = evidence.settings.get("yolo_threshold", 0.25)

    st.markdown(
        f"Both detectors read the same VV radar. At {threshold} confidence, YOLO found **{yolo}** targets across the passes and CFAR also found **{both}** of them. "
        f"Going the other way, YOLO found only {both} of CFAR's {cfar}. So YOLO rarely fires, and when it does CFAR nearly always agrees. "
        "That makes it a useful confirmation but not a replacement. This doesn't say which one is right about the rest."
    )
    tiles = st.columns(3)
    tiles[0].metric("YOLO targets CFAR also found", f"{both} of {yolo}")
    tiles[1].metric("CFAR targets YOLO also found", f"{both} of {cfar}")
    tiles[2].metric("Bright in the VH channel", f"{vh} of {measured}", help=f"VH is a separate radar measurement. 'Bright' means above {evidence.settings.get('vh_confirm_percentile', 99):.0f}% of random open-water points in that pass.")

    figure = go.Figure()
    labels = [pass_time(pd.Timestamp(item["timestamp"])) for item in passes]
    for name, key, colour in [("Both", "both", SERIES_COLOURS[0]), ("CFAR only", "cfar_only", SERIES_COLOURS[1]), ("YOLO only", "yolo_only", SERIES_COLOURS[2])]:
        figure.add_trace(go.Bar(
            x=labels, y=[item[key] for item in passes], name=name,
            marker={"color": colour, "line": {"color": "#1a1a19", "width": 2}},
            hovertemplate="%{y} targets<extra>" + name + "</extra>",
        ))
    figure.update_layout(barmode="stack", bargap=0.35)
    style_figure(figure, 320, "Targets")
    show_figure(figure)

    render_review_check(frame)

    thresholds = sorted(passes[0].get("sensitivity", {}))
    if thresholds:
        rows = []
        for value in thresholds:
            found = sum(item["sensitivity"][value]["yolo"] for item in passes)
            agreed = sum(item["sensitivity"][value]["both"] for item in passes)
            rows.append({"YOLO threshold": value, "YOLO targets": found, "Also found by CFAR": agreed, "YOLO only": found - agreed})
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

    fixed_count = int(targets["fixed_likely"].sum()) if "fixed_likely" in targets else 0
    measured_passes = int(targets["passes_measured"].max()) if "passes_measured" in targets else 0
    if fixed_count:
        st.caption(
            f"Separately, {fixed_count} targets are bright at exactly the same spot in all {measured_passes} passes measured, which includes one pass outside the contract. "
            "They may be structures, coastline features or permanent moorings rather than ships."
        )

    only_yolo = targets[targets["yolo_only"]]
    if not only_yolo.empty:
        st.markdown("**Found by YOLO only**")
        columns = st.columns(4)
        for column, row in zip(columns, only_yolo.head(4).to_dict("records")):
            info = evidence.pass_info(row["scene_id"]) or {}
            column.image(row["chip_vv"], width="stretch")
            column.caption(
                f"{row['id']}, confidence {row['yolo_confidence']:.2f}. {row['vv_contrast_db']} dB above the sea, "
                f"where this pass's sea clutter reaches {info.get('vv_clutter_p99_db', '?')} dB."
            )
        st.caption("A high YOLO score isn't proof on its own: compare each one's brightness with the clutter level.")

    if metrics:
        st.markdown("**The model's own test scores**")
        score_tiles = st.columns(4)
        for tile, (label, key) in zip(score_tiles, [("Precision", "precision"), ("Recall", "recall"), ("mAP50", "mAP50"), ("mAP50-95", "mAP50_95")]):
            tile.metric(label, f"{metrics[key]:.3f}")
        model = evidence.model
        st.caption(
            f"{metrics.get('model')} trained on {model.get('trained_on')} for {model.get('epochs')} epochs, tested on {metrics.get('n_images'):,} images from {metrics.get('dataset')}. "
            "These scores are on HRSID's finer-resolution images, so they say nothing about accuracy in the Gulf."
        )
    st.caption(f"Second opinion built {evidence.built_at[:10]}. {evidence.source}.")


def render(frame: pd.DataFrame, manifest: dict | None, metrics: dict | None, evidence: Evidence | None, checks: dict | None = None) -> None:
    if manifest:
        render_provenance(manifest)
        render_funnel(manifest)
    if metrics:
        render_precision(metrics)
    render_fishing_watch_check(frame, checks)
    st.subheader("Limits")
    st.markdown(
        "- **The AIS check isn't ours and isn't instant.** It's Fishing Watch's matching, about 5 days behind, so the newest pass may have none yet.\n"
        "- **Missed ships can't be counted.** There's no ground truth for the Gulf, so recall is unknown.\n"
        "- **Each pass is a snapshot**, days apart. Radar shows no speed or heading, so ships can't be followed between passes.\n"
        "- **Only one part of the Gulf is covered:** Jebel Ali, Khalifa Port and their approaches.\n"
        "- **Length is approximate**, good to about ±20 m at 10 m pixels.\n"
        "- **AIS positions are rounded to about 1 km.** The replay moves any that land on the shore to the nearest water, using OpenStreetMap, and leaves out the few too far from water to be real. Its lines between hours are estimates."
    )
    render_second_opinion(frame, evidence)
    if manifest and manifest.get("reproduce"):
        st.subheader("Rebuild it yourself")
        st.code("\n".join(manifest["reproduce"]), language="bash")
        st.code(
            "cd dashboard/pipeline\n"
            "uv run python yolo_scan.py --weights <best.pt> --out <folder>\n"
            "uv run python build_evidence.py --weights <best.pt> --runs <folder>",
            language="bash",
        )
