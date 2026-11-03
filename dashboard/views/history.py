"""Ship history: who has been near the two ports, and which checkable facts about them are worth a closer look."""
import pandas as pd
import pydeck as pdk
import streamlit as st

from components import (
    FLAG_COLUMN_PX,
    GFW_ATTRIBUTION,
    MAP_HEIGHT_PX,
    RING_RGB,
    SHIP_HEX,
    SHIP_RGB,
    deck,
    legend,
    map_view,
    point_layer,
    reported,
    ship_type_label,
)

WORTH_CHECKING = "Worth checking"
WITH_NOTES = "With notes too"
ALL_SHIPS = "All ships"
LEVEL_LABELS = {"strong": "🔴 Strong", "check": "🟠 Check", "note": "🟡 Note", "none": "–"}
LEVEL_ORDER = {"strong": 0, "check": 1, "note": 2, "none": 3}
ROUTE_MAP_PX = MAP_HEIGHT_PX - 100


def ships_frame(history: dict) -> pd.DataFrame:
    frame = pd.DataFrame(history["ships"])
    frame["level"] = [reasons[0]["level"] if reasons else "none" for reasons in frame["reasons"]]
    frame["level_label"] = frame["level"].map(LEVEL_LABELS)
    frame["top_reason"] = [reasons[0]["text"] if reasons else "" for reasons in frame["reasons"]]
    frame["reason_count"] = frame["reasons"].map(len)
    frame["type_label"] = frame["type"].map(ship_type_label)
    frame["near_label"] = [", ".join(near) if near else "Elsewhere in the area" for near in frame["near"]]
    frame["country_label"] = [", ".join(countries) for countries in frame["countries"]]
    frame["name_label"] = reported(frame["name"], "Name not reported")
    frame["flag_label"] = reported(frame["flag"])
    frame["imo_label"] = reported(frame["imo"])
    frame["mmsi_label"] = reported(frame["mmsi"])
    frame["order"] = frame["level"].map(LEVEL_ORDER)
    return frame.sort_values(["order", "reason_count", "port_calls_12m"], ascending=[True, False, False])


def filtered(frame: pd.DataFrame) -> pd.DataFrame:
    show_column, near_column, type_column, search_column = st.columns([3, 2, 2, 2])
    show = show_column.radio("Show", [WORTH_CHECKING, WITH_NOTES, ALL_SHIPS], horizontal=True, key="hist_show")
    nears = near_column.multiselect("Near", sorted({port for near in frame["near"] for port in near}), key="hist_near", placeholder="Whole area")
    types = type_column.multiselect("Type", sorted(frame["type_label"].unique()), key="hist_type", placeholder="All types")
    search = search_column.text_input("Search name, IMO or MMSI", key="hist_search").strip().lower()

    result = frame
    if show == WORTH_CHECKING:
        result = result[result["level"].isin(["strong", "check"])]
    elif show == WITH_NOTES:
        result = result[result["level"] != "none"]
    if nears:
        result = result[[bool(set(near) & set(nears)) for near in result["near"]]]
    if types:
        result = result[result["type_label"].isin(types)]
    if search:
        haystack = result["name_label"].str.lower() + " " + result["imo"].fillna("") + " " + result["mmsi"].fillna("")
        result = result[haystack.str.contains(search, regex=False)]
    return result


def route_map(row: pd.Series) -> None:
    calls = row["recent_calls"]
    points = [{"lat": call["lat"], "lon": call["lon"], "tooltip": f"<b>{call['port']}</b> ({call['country']})<br/>{call['start'][:10]} to {call['end'][:10]}"} for call in calls]
    last_seen = pd.DataFrame([{"lat": row["lat"], "lon": row["lon"], "tooltip": f"<b>Last seen here</b><br/>{row['last_seen']} UTC"}])
    if not points:
        st.pydeck_chart(deck([point_layer(last_seen, RING_RGB, 6)], map_view(last_seen)), height=ROUTE_MAP_PX, key="hist_map")
        return
    stops = pd.DataFrame(points)
    path = pd.DataFrame([{"path": [[call["lon"], call["lat"]] for call in calls] + [[row["lon"], row["lat"]]]}])
    layers = [
        pdk.Layer("PathLayer", path, get_path="path", get_color=[*SHIP_RGB, 150], get_width=2, width_units=pdk.types.String("pixels")),
        point_layer(stops, SHIP_RGB, 5),
        point_layer(last_seen, RING_RGB, 6),
    ]
    # Leave a margin, so ports at the edge of the route aren't cut off.
    st.pydeck_chart(deck(layers, map_view(pd.concat([stops, last_seen]), fit_px=ROUTE_MAP_PX - 110)), height=ROUTE_MAP_PX, key="hist_map")
    legend([(SHIP_HEX, "Port call", False), ("#f0efec", "Last seen", False)])
    st.caption("Straight lines between port calls, not the route it actually sailed.")


def identity_lines(row: pd.Series) -> list[str]:
    length = "" if pd.isna(row["length_m"]) else f", about {row['length_m']:.0f} m"
    return [
        f"**{row['type_label']}**{length}. Flag: {row['flag_label']}.",
        f"IMO {row['imo_label']} · MMSI {row['mmsi_label']}",
        f"Near: {row['near_label']}. Last seen in this area {row['last_seen']} UTC.",
    ]


def render_detail(row: pd.Series) -> None:
    st.subheader(row["name_label"])
    info_column, map_column = st.columns([2, 3], gap="large")
    with info_column:
        for line in identity_lines(row):
            st.markdown(line)
        st.markdown(f"**{row['port_calls_12m']} port calls** in the last 12 months" + (f", in {row['country_label']}." if row["country_label"] else "."))
        if row["loitering_hours_12m"]:
            st.markdown(f"About {row['loitering_hours_12m'] / 24:.0f} days loitering at sea in that time.")
        if len(row["identities"]) > 1:
            st.markdown("**Names and flags it has reported:**")
            for identity in row["identities"]:
                st.markdown(f"- {identity['name'] or 'No name'}, {identity['flag'] or 'no flag'}: {identity['from']} to {identity['to']}")
        if row["reasons"]:
            st.markdown("**Worth a closer look because:**")
            for reason in row["reasons"]:
                st.markdown(f"- {LEVEL_LABELS[reason['level']]}: {reason['text']} *Source: {reason['source']}.*")
        else:
            st.markdown("Nothing in these sources stands out.")
    with map_column:
        route_map(row)
    calls = row["recent_calls"]
    if calls:
        st.dataframe(
            pd.DataFrame(calls).iloc[::-1].assign(start=lambda table: table["start"].str.replace("T", " "), end=lambda table: table["end"].str.replace("T", " ")),
            hide_index=True,
            width="stretch",
            column_order=["port", "country", "start", "end", "hours"],
            column_config={
                "port": st.column_config.TextColumn("Port", width="medium"),
                "country": "Country",
                "start": "Arrived (UTC)",
                "end": "Left (UTC)",
                "hours": st.column_config.NumberColumn("Hours", format="%.0f"),
            },
        )


def render(history: dict | None) -> None:
    if history is None:
        st.info("The ship history hasn't been built yet. Run dashboard/pipeline/build_gfw.py.")
        return
    frame = ships_frame(history)
    strong = int((frame["level"] == "strong").sum())
    check = int((frame["level"] == "check").sum())
    sanctioned = sum(any(reason["kind"] == "sanctions" for reason in reasons) for reasons in frame["reasons"])
    total_tile, strong_tile, check_tile, list_tile = st.columns(4)
    total_tile.metric(f"Ships here in the last {history['window_days']} days", f"{len(frame):,}")
    strong_tile.metric("Strong reason to check", f"{strong:,}")
    check_tile.metric("Other reasons to check", f"{check:,}")
    list_tile.metric("Sanctions list matches", f"{sanctioned:,}", help=f"Checked against {history['sanctions_list_size']:,} vessels on the US OFAC list.")
    st.warning(
        "These are reasons to look closer, not accusations. Each one is a checkable fact with its source. "
        "A ship can have good reasons for all of them: trade between the UAE and Iran is common, for example, and ships get sold and renamed. "
        "A blank record doesn't clear a ship either, because these sources can miss things. "
        "Only ships broadcasting AIS appear here: a ship that never transmits has no identity to look up.",
        icon="⚠️",
    )

    shown = filtered(frame)
    st.caption(f"{len(shown):,} of {len(frame):,} ships.")
    event = st.dataframe(
        shown,
        hide_index=True,
        width="stretch",
        height=420,
        on_select="rerun",
        selection_mode="single-row",
        key="hist_table",
        column_order=["level_label", "name_label", "flag_label", "type_label", "length_m", "near_label", "top_reason", "reason_count", "port_calls_12m", "imo_label"],
        column_config={
            "level_label": "Level",
            "name_label": st.column_config.TextColumn("Ship", width="medium"),
            "flag_label": st.column_config.TextColumn("Flag", width=FLAG_COLUMN_PX),
            "type_label": "Type",
            # A plain number column would show a blank length as "None".
            "length_m": st.column_config.ProgressColumn("Length", min_value=0, max_value=int(frame["length_m"].max()), format="%d m"),
            "near_label": "Near",
            "top_reason": st.column_config.TextColumn("Main reason", width="large"),
            "reason_count": st.column_config.NumberColumn("Reasons", format="%d"),
            "port_calls_12m": st.column_config.NumberColumn("Port calls, 12 months", format="%d"),
            "imo_label": "IMO",
        },
    )
    rows = event.selection.rows if event and event.selection else []
    if rows and rows[0] < len(shown):
        render_detail(shown.iloc[rows[0]])
    else:
        st.info("Select a ship to see its port calls, route and reasons.")
    st.markdown(GFW_ATTRIBUTION)
    st.caption(f"Port calls and identity from Global Fishing Watch, from {history['history_from']}. Sanctions from the US Treasury OFAC SDN list. Built {history['built_at'][:10]}.")
