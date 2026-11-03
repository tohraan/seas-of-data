"""Review queue: which detections to check by eye next, and the verdicts so far. Read-only."""
from pathlib import Path

import pandas as pd
import streamlit as st

from analysis import review_queue
from components import cached_thumbnail, pass_time
from data import load_labels, resolve_chip

PAGE_SIZE = 8


def render(frame: pd.DataFrame, directory: Path, metrics: dict | None) -> None:
    reviewed = frame[frame["review"] != "unreviewed"]
    counts = frame["review"].value_counts()
    done_tile, yes_tile, no_tile, unsure_tile, left_tile = st.columns(5)
    done_tile.metric("Reviewed", f"{len(reviewed)} of {len(frame)}")
    yes_tile.metric("Looks like a ship", int(counts.get("confirmed", 0)))
    no_tile.metric("Not a ship", int(counts.get("rejected", 0)))
    unsure_tile.metric("Unsure", int(counts.get("unsure", 0)))
    left_tile.metric("Still to review", int(counts.get("unreviewed", 0)))
    if metrics:
        st.caption(metrics.get("not", ""))

    st.subheader("Next to review")
    st.markdown("Strongest evidence first: the ship-class rule, YOLO also finding it, and brightness in the VH channel, then overall brightness.")
    queue = review_queue(frame)
    if queue.empty:
        st.info("Every detection has been reviewed.")
    else:
        pages = max(1, (len(queue) + PAGE_SIZE - 1) // PAGE_SIZE)
        page = st.number_input(f"Page, of {pages}", 1, pages, 1, key="review_page") if pages > 1 else 1
        batch = queue.iloc[(page - 1) * PAGE_SIZE : page * PAGE_SIZE]
        columns = st.columns(4)
        for index, (_, row) in enumerate(batch.iterrows()):
            with columns[index % 4].container(border=True):
                chip = resolve_chip(row["chip"], directory)
                if chip:
                    st.image(str(chip), width="stretch")
                st.markdown(f"**{row['id']}**")
                length = "length unknown" if pd.isna(row["length_m"]) else f"about {row['length_m']:.0f} m"
                st.markdown(f"{row['class_label']}, {length}")
                st.caption(f"{row['why']}. {row['location']}. Pass {pass_time(row['timestamp'])}.")
                st.markdown(f"[Open]({'?id=' + row['id']})")

    st.subheader("Verdicts so far")
    labels = load_labels(directory)
    if labels.empty:
        st.info("No review file yet.")
        return
    table = labels.merge(frame[["id", "chip", "class_label", "length_m", "location"]], on="id", how="left")
    verdict_filter = st.multiselect("Verdict", sorted(labels["verdict"].unique()), key="review_verdict", placeholder="All verdicts")
    if verdict_filter:
        table = table[table["verdict"].isin(verdict_filter)]
    table["thumb"] = [cached_thumbnail(chip, str(directory)) for chip in table["chip"]]
    st.dataframe(
        table,
        hide_index=True,
        width="stretch",
        height=420,
        row_height=64,
        column_order=["thumb", "id", "verdict", "class_label", "length_m", "location", "reviewer"],
        column_config={
            "thumb": st.column_config.ImageColumn("Radar", width="small"),
            "id": st.column_config.TextColumn("ID", width="medium"),
            "verdict": "Verdict",
            "class_label": "Class",
            "length_m": st.column_config.NumberColumn("Length (m)", format="%d"),
            "location": st.column_config.TextColumn("Location", width="large"),
            "reviewer": "Reviewer",
        },
    )
