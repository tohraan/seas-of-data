"""Directory of every detection, for analysts and journalists: map, table, one detection's evidence, and downloads."""
from pathlib import Path

import pandas as pd
import streamlit as st

from analysis import (
    CLASS_LABELS,
    REVIEW_LABELS,
    SIZE_LABELS,
    SIZE_RANGES,
    possible_dark,
    same_spot,
    sort_for_table,
    to_csv,
    to_geojson,
)
from components import (
    ATTRIBUTION,
    DARK_HEX,
    DARK_RGB,
    FIXED_HEX,
    FIXED_RGB,
    MAP_HEIGHT_PX,
    SHIP_HEX,
    SHIP_RGB,
    UNCERTAIN_HEX,
    UNCERTAIN_RGB,
    cached_radar_image,
    cached_thumbnail,
    deck,
    legend,
    map_view,
    pass_time,
    point_layer,
    radar_layer,
)
from data import Evidence, resolve_chip

TABLE_COLUMNS = [
    "thumb", "id", "class_label", "size_label", "length_m", "contrast_db", "location", "seen",
    "review_label", "check_label", "vh_label", "ais_label", "timestamp",
]


def filtered(frame: pd.DataFrame) -> pd.DataFrame:
    class_column, size_column, area_column, review_column, search_column = st.columns([2, 2, 2, 2, 2])
    classes = class_column.multiselect(
        "Radar class", list(CLASS_LABELS.values()), default=["Ship"], key="ex_class", placeholder="All classes",
    )
    sizes = size_column.multiselect(
        "Size", [SIZE_LABELS[key] for key in SIZE_RANGES], key="ex_size", placeholder="All sizes",
    )
    zones = area_column.multiselect("Area", sorted(frame["zone"].unique()), key="ex_zone", placeholder="All areas")
    reviews = review_column.multiselect("Review", list(REVIEW_LABELS.values()), key="ex_review", placeholder="Any review")
    search = search_column.text_input("Search by ID", key="ex_search").strip().lower()

    result = frame
    if classes:
        result = result[result["class_label"].isin(classes)]
    if sizes:
        result = result[result["size_label"].isin(sizes)]
    if zones:
        result = result[result["zone"].isin(zones)]
    if reviews:
        result = result[result["review_label"].isin(reviews)]
    if search:
        result = result[result["id"].str.lower().str.contains(search, regex=False)]
    return result


def map_points(detections: pd.DataFrame) -> pd.DataFrame:
    labelled = detections.copy()
    labelled["tooltip"] = [
        f"<b>{cls}</b> · {identifier}<br/>{location}<br/>{size}, {length}<br/>Pass {pass_time(moment)}<br/>AIS: {ais}"
        for cls, identifier, location, size, length, moment, ais in zip(
            labelled["class_label"], labelled["id"], labelled["location"], labelled["size_label"],
            labelled["length_m"].map(lambda v: "length unknown" if pd.isna(v) else f"about {v:.0f} m"),
            labelled["timestamp"], labelled["ais_label"],
        )
    ]
    # Only these reach the browser: the raw nullable columns would serialise as invalid JSON NaN.
    labelled["is_dark"] = possible_dark(labelled)
    return labelled[["id", "lon", "lat", "radar_class", "is_dark", "tooltip"]]


def render_map(shown: pd.DataFrame, evidence: Evidence | None, scene_id: str | None, chosen_id: str | None, show_radar: bool) -> None:
    points = map_points(shown)
    layers = []
    latest_pass = evidence.passes[-1] if evidence and evidence.passes else None
    info = (evidence.pass_info(scene_id) if evidence and scene_id else latest_pass) if show_radar else None
    if info:
        image = cached_radar_image(info["image"])
        if image:
            layers.append(radar_layer(image, info["corners"]))
    layers += [
        point_layer(points[(points["radar_class"] == "uncertain") & ~points["is_dark"]], UNCERTAIN_RGB, 4),
        point_layer(points[(points["radar_class"] == "ship") & ~points["is_dark"]], SHIP_RGB, 6),
        point_layer(points[(points["radar_class"] == "likely_fixed") & ~points["is_dark"]], FIXED_RGB, 6, 2),
        point_layer(points[points["is_dark"]], DARK_RGB, 8, 2),
    ]
    if chosen_id:
        layers.append(point_layer(points[points["id"] == chosen_id], [0, 0, 0, 0], 13, 3))
    st.pydeck_chart(deck(layers, map_view(shown)), height=MAP_HEIGHT_PX)
    items = [
        (SHIP_HEX, "Ship", False),
        (UNCERTAIN_HEX, "Uncertain", False),
        (FIXED_HEX, "Likely fixed", True),
    ]
    if points["is_dark"].any():
        items.append((DARK_HEX, "Possibly dark (real AIS check)", True))
    legend(items)
    if info:
        st.caption(f"Radar image: Sentinel-1 VV, {info['scene_id']}. {ATTRIBUTION}")
    else:
        st.caption(ATTRIBUTION)


def fact(label: str, value: str) -> None:
    st.markdown(f"**{label}:** {value}")


def render_detail(row: pd.Series, frame: pd.DataFrame, directory: Path, total_passes: int) -> None:
    st.subheader(f"{row['class_label']} · {row['id']}")
    chip = resolve_chip(row["chip"], directory)
    context = resolve_chip(row["chip_context"], directory)
    has_vh = isinstance(row["chip_vh"], str)
    columns = st.columns(3 if has_vh else 2)
    if chip:
        columns[0].image(str(chip), caption="Radar VV, 1.3 km across", width="stretch")
    if context:
        columns[1].image(str(context), caption="Surroundings, 7.7 km across", width="stretch")
    if has_vh:
        columns[2].image(row["chip_vh"], caption="Radar VH, 1 km across", width="stretch")
    if not chip and not context:
        st.caption("This file has no radar images.")
    else:
        st.caption("Image axes follow the satellite's track, not north.")

    fact("Location", f"{row['location']} ({row['lat']:.4f} N, {row['lon']:.4f} E)")
    if pd.notna(row["length_m"]):
        fact("Size", f"{row['size_label']}, about {row['length_m']:.0f} m (good to about ±20 m)")
    if pd.notna(row["contrast_db"]):
        fact("Brightness", f"{row['contrast_db']:.1f} dB above the surrounding sea")
    fact("Same spot", f"seen in {int(row['persistence'])} of {total_passes} passes")
    fact("Visual review", row["review_label"])
    fact("AIS", row["ais_label"])
    if row["check_label"] != "Not run":
        yolo = "not found" if pd.isna(row["yolo_confidence"]) else f"found at {row['yolo_confidence']:.2f}"
        fact("Second opinion", f"YOLO {yolo}; bright in VH: {row['vh_label'].lower()}")
    if pd.notna(row["axis_deg"]):
        opposite = (row["axis_deg"] + 180) % 360
        fact("Hull direction", f"about {row['axis_deg']:.0f}° or {opposite:.0f}°. Radar can't tell which way it points, or whether it's moving.")
    if row["fixed_likely"] is True or row["fixed_likely"] == 1:
        fact("Possibly fixed", f"bright at this exact spot in all {int(row['passes_measured'])} passes measured, so it may be a structure or a mooring rather than a ship")
    others = same_spot(frame, row)
    if not others.empty:
        fact("Other passes here", ", ".join(f"{identifier} ({moment:%d %b})" for identifier, moment in zip(others["id"], others["timestamp"])))
    st.caption(f"Pass {pass_time(row['timestamp'])}. Scene {row['scene_id']}." + (f" Product {row['product']}." if isinstance(row["product"], str) else ""))
    link_column, map_column = st.columns(2)
    link_column.markdown(f"[Link to this detection](?id={row['id']})")
    map_column.markdown(f"[Open in OpenStreetMap]({row['map_url']})")


def citation(frame: pd.DataFrame, manifest: dict | None) -> str:
    start, end = frame["timestamp"].min(), frame["timestamp"].max()
    generated = (manifest or {}).get("generated_utc", "")[:10]
    attribution = (manifest or {}).get("attribution", "Contains modified Copernicus Sentinel data (2026).")
    built = f", version of {generated}" if generated else ""
    return (
        f"Seas of Data (2026). Gulf radar ship detections: {len(frame)} detections from {frame['scene_id'].nunique()} "
        f"Sentinel-1 passes, {start:%d %b %Y} to {end:%d %b %Y}, Jebel Ali and Khalifa Port{built}. {attribution}"
    )


def render(selected: pd.DataFrame, frame: pd.DataFrame, evidence: Evidence | None, scene_id: str | None, directory: Path, manifest: dict | None, total_passes: int) -> None:
    shown = sort_for_table(filtered(selected))
    radar_toggle = st.toggle("Show the radar image", value=evidence is not None, key="ex_radar", disabled=evidence is None)
    map_column, detail_column = st.columns([3, 2], gap="large")

    table = shown.copy()
    table["thumb"] = [cached_thumbnail(chip, str(directory)) for chip in table["chip"]]
    table["seen"] = [f"{int(value)} of {total_passes}" for value in table["persistence"]]
    table["length_m"] = table["length_m"].round()  # the column format would otherwise cut 178.9 down to 178
    st.caption(f"{len(shown)} of {len(selected)} detections in this view. Select a row to see its evidence.")
    longest = float(selected["length_m"].max()) if selected["length_m"].notna().any() else 1.0
    event = st.dataframe(
        table[TABLE_COLUMNS],
        hide_index=True,
        width="stretch",
        height=460,
        row_height=64,
        on_select="rerun",
        selection_mode="single-row",
        key="ex_table",
        column_config={
            "thumb": st.column_config.ImageColumn("Radar", width="small"),
            "id": st.column_config.TextColumn("ID", width="medium"),
            "class_label": "Class",
            "size_label": "Size",
            "length_m": st.column_config.ProgressColumn("Length", format="%d m", min_value=0, max_value=longest),
            "contrast_db": st.column_config.NumberColumn("Brightness (dB)", format="%.1f"),
            "location": st.column_config.TextColumn("Location", width="large"),
            "seen": "Same spot in",
            "review_label": "Visual review",
            "check_label": "YOLO check",
            "vh_label": "Bright in VH",
            "ais_label": "AIS",
            "timestamp": st.column_config.DatetimeColumn("Pass (UTC)", format="DD MMM HH:mm"),
        },
    )

    rows = event.selection.rows if event and event.selection else []
    chosen_id = None
    if rows and rows[0] < len(shown):
        chosen_id = shown.iloc[rows[0]]["id"]
        st.query_params["id"] = chosen_id
    elif st.query_params.get("id") in set(frame["id"]):
        chosen_id = st.query_params.get("id")

    with map_column:
        render_map(shown, evidence, scene_id, chosen_id, radar_toggle)
    with detail_column:
        if chosen_id:
            render_detail(frame[frame["id"] == chosen_id].iloc[0], frame, directory, total_passes)
        else:
            st.info("Select a row in the table below to see its radar images and evidence.")

    if not shown.empty:
        csv_column, geojson_column, _ = st.columns([1, 1, 4])
        csv_column.download_button("Download CSV", to_csv(shown), "seas_of_data_detections.csv", "text/csv", key="ex_csv")
        geojson_column.download_button("Download GeoJSON", to_geojson(shown), "seas_of_data_detections.geojson", "application/geo+json", key="ex_geojson")
    with st.expander("How to cite this data"):
        st.code(citation(selected, manifest), language=None, wrap_lines=True)
