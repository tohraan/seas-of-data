"""Buoy siting: where one or more buoys would cover the most real detections. This ties the CAD buoy to the data."""
import pandas as pd
import streamlit as st

from analysis import haversine_km, radio_horizon_km, rank_sites, unique_spots
from components import (
    ATTRIBUTION,
    FIXED_RGB,
    MAP_HEIGHT_PX,
    MUTED,
    RING_RGB,
    SHIP_HEX,
    SHIP_RGB,
    UNCERTAIN_RGB,
    circle_layer,
    deck,
    legend,
    map_view,
    point_layer,
)

DEFAULT_ANTENNA_M = 3.8
DEFAULT_CAMERA_KM = 5.0
DEFAULT_SHIP_ANTENNA_M = 15


def render(frame: pd.DataFrame, specs: dict | None) -> None:
    ships = frame[frame["radar_class"] == "ship"]
    if ships.empty:
        st.info("No ship-class detections to site a buoy against.")
        return
    spots = unique_spots(ships.sort_values("timestamp", ascending=False))
    antenna_m = (specs or {}).get("ais_antenna_above_water_m", DEFAULT_ANTENNA_M)
    # Rounded to the slider's half-kilometre steps.
    camera_default = round((specs or {}).get("camera_recognition_range_km", DEFAULT_CAMERA_KM) * 2) / 2

    count_column, ship_column, camera_column = st.columns(3)
    buoys = count_column.slider("Number of buoys", 1, 3, 1, key="site_buoys")
    ship_antenna = ship_column.slider(
        "Ship's AIS antenna height (m)", 3, 40, DEFAULT_SHIP_ANTENNA_M, key="site_ship_antenna",
        help="Assumed. Large ships carry antennas higher up, so they're heard from further away.",
    )
    camera_km = camera_column.slider(
        "Camera range (km)", 1.0, 15.0, camera_default, 0.5, key="site_camera",
        help="Range for recognising a 60 m ship in clear air, from cad/buoy/DATASHEET.md." if specs else "Placeholder until the buoy's numbers are calculated.",
    )
    ais_km = radio_horizon_km(antenna_m, ship_antenna)
    sites = rank_sites(spots, ais_km, camera_km, buoys)
    if not sites:
        st.info("No usable site.")
        return
    best = sites[-1]

    ais_tile, camera_tile, range_tile = st.columns(3)
    ais_tile.metric("In AIS range", f"{best['primary_total']} of {len(spots)} spots")
    camera_tile.metric("In camera range", f"{best['secondary_total']} of {len(spots)} spots")
    range_tile.metric("AIS range", f"{ais_km:.0f} km", help=f"Radio horizon between a {antenna_m:.1f} m buoy antenna and a {ship_antenna} m ship antenna.")

    lat = spots["lat"].to_numpy(float)
    lon = spots["lon"].to_numpy(float)
    in_range = pd.Series(False, index=spots.index)
    for site in sites:
        in_range |= pd.Series(haversine_km(lat, lon, site["lat"], site["lon"]) <= ais_km, index=spots.index)
    points = spots.assign(
        tooltip=[f"<b>{identifier}</b><br/>{location}" for identifier, location in zip(spots["id"], spots["location"])]
    )[["lon", "lat", "tooltip"]]
    centres = pd.DataFrame(sites)[["lat", "lon"]]
    centres["tooltip"] = [f"<b>Proposed buoy {index + 1}</b><br/>{site['lat']:.4f} N, {site['lon']:.4f} E" for index, site in enumerate(sites)]

    layers = [
        circle_layer(centres, ais_km, SHIP_RGB, 18),
        circle_layer(centres, camera_km, FIXED_RGB, 36),
        point_layer(points[~in_range], UNCERTAIN_RGB, 5),
        point_layer(points[in_range], SHIP_RGB, 5),
        point_layer(centres, RING_RGB, 7, 2, [13, 13, 13]),
    ]
    st.pydeck_chart(deck(layers, map_view(spots)), height=MAP_HEIGHT_PX)
    legend([
        (SHIP_HEX, "Ship-class spot in AIS range", False),
        (MUTED, "Out of range", False),
        ("#f0efec", "Proposed buoy", False),
    ])
    st.caption(f"The blue circle is AIS range and the amber circle is camera range. {ATTRIBUTION}")

    st.dataframe(
        pd.DataFrame([
            {
                "Buoy": index + 1,
                "Latitude": round(site["lat"], 4),
                "Longitude": round(site["lon"], 4),
                "New spots in AIS range": site["new_primary"],
                "New spots in camera range": site["new_secondary"],
            }
            for index, site in enumerate(sites)
        ]),
        hide_index=True,
        width="stretch",
    )
    st.caption(
        "Each site is picked in turn for the most new spots in AIS range, then in camera range. Candidates are detected spots at least 1 km from land, "
        "because those are known to be water. A spot seen in several passes counts once. Water depth, shipping lanes and permits aren't checked, so this is a starting point for a real survey. "
        "Ship-class detections from all passes. Buoy heights and ranges come from the design calculation in cad/buoy/DATASHEET.md: the buoy is a design and hasn't been built."
    )
