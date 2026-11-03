"""Port watch, for harbour and port operations: ship-class counts by size at each pass, and when the next pass is due."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from analysis import SIZE_LABELS, SIZE_RANGES, expected_next_passes
from components import (
    INK_SECONDARY,
    SERIES_COLOURS,
    SIZE_RAMP,
    pass_time,
    show_figure,
    style_figure,
)
from data import ContractError, load_coverage, load_port_activity


def port_chart(rows: pd.DataFrame) -> go.Figure:
    figure = go.Figure()
    labels = rows["date"].dt.strftime("%d %b")
    totals = rows["vessel_count"].tolist()
    sized = bool(rows["by_size"].apply(lambda value: isinstance(value, dict)).all())
    if sized:
        for key in SIZE_RANGES:
            figure.add_trace(go.Bar(
                x=labels,
                y=[value.get(key, 0) for value in rows["by_size"]],
                name=f"{SIZE_LABELS[key]} ({SIZE_RANGES[key]})",
                marker={"color": SIZE_RAMP[key], "line": {"color": "#1a1a19", "width": 2}},
                hovertemplate="%{y} ships<extra>" + SIZE_LABELS[key] + "</extra>",
            ))
    else:
        figure.add_trace(go.Bar(x=labels, y=totals, name="Ships", marker={"color": SERIES_COLOURS[0], "cornerradius": 4}))
    # Totals sit above the stacks, including the zeros, which would otherwise look like missing data.
    figure.add_trace(go.Scatter(
        x=labels, y=totals, mode="text", text=totals, textposition="top center",
        textfont={"color": INK_SECONDARY, "size": 13}, showlegend=False, hoverinfo="skip", cliponaxis=False,
    ))
    figure.update_layout(barmode="stack", bargap=0.35)
    style_figure(figure, 320, "Ship-class detections", legend_visible=sized)
    figure.update_layout(legend={"y": 1.24, "font": {"size": 11}}, margin={"t": 64})
    if max(totals) <= 12:  # these are counts, so no ticks at 0.5
        figure.update_yaxes(dtick=1)
    return figure


def render(frame: pd.DataFrame) -> None:
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
    now = pd.Timestamp.now(tz="UTC")
    last_seen = frame["timestamp"].max()
    upcoming = expected_next_passes(frame["timestamp"], now)
    last_tile, next_tile, count_tile = st.columns(3)
    last_tile.metric("Last observed", pass_time(last_seen), help=f"{(now - last_seen).total_seconds() / 3600:.0f} hours ago")
    if load_coverage():
        count_tile.caption("Acquisition list available in coverage.json.")
    next_tile.metric("Next pass expected", pass_time(upcoming[0]) if upcoming else "Unknown", help="Worked out from the 12-day repeat of the passes so far, not from a published schedule.")
    count_tile.metric("Passes so far", frame["scene_id"].nunique())

    columns = st.columns(2, gap="large")
    for column, port in zip(columns, sorted(activity["port"].unique())):
        rows = activity[activity["port"] == port].sort_values("date")
        with column:
            st.subheader(port)
            latest = rows.iloc[-1]
            uncertain = latest["uncertain_count"]
            extra = "" if pd.isna(uncertain) else f", plus {int(uncertain)} uncertain"
            st.markdown(f"**{int(latest['vessel_count'])} ship-class** at the latest pass{extra}.")
            show_figure(port_chart(rows))

    st.dataframe(
        activity.sort_values(["date", "port"]),
        hide_index=True,
        width="stretch",
        column_order=["date", "port", "vessel_count", "uncertain_count", "activity_index"],
        column_config={
            "date": st.column_config.DateColumn("Pass", format="DD MMM"),
            "port": "Port",
            "vessel_count": st.column_config.NumberColumn("Ship-class", format="%d"),
            "uncertain_count": st.column_config.NumberColumn("Uncertain", format="%d"),
            "activity_index": st.column_config.NumberColumn("% of this port's median", format="%.0f"),
        },
    )
    low, high = int(activity["vessel_count"].min()), int(activity["vessel_count"].max())
    st.caption(
        f"Each port box includes its approaches. Counts are small ({low}-{high} ships per pass), so this is a baseline, not a trend. "
        f"Source: contracts/{loaded.path.name}"
    )
