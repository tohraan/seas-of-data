"""The water checks, on small made-up maps. The file at the end checks the real shipped data."""
import itertools
import json
from pathlib import Path

import numpy as np
import pytest

from gfw_logic import MAX_LINE_HOURS, movement_rows, ship_reasons
from water import (
    EAST,
    LINE_CLIP_KM,
    ROUNDING_KM,
    WEST,
    WaterMap,
    clean_positions,
    named_waterways,
    navigable_water,
)

DERIVED = Path(__file__).resolve().parents[2] / "derived"
WEST_EDGE, NORTH_EDGE, CELL = 55.0, 25.2, 0.001


def grid_map() -> WaterMap:
    """Sea across the north, land across the south, and a wall of land from the shore nearly up to the top of the sea."""
    water = np.zeros((200, 200), dtype=bool)
    water[:100, :] = True
    water[:90, 90:112] = False
    return WaterMap(water, WEST_EDGE, NORTH_EDGE, CELL)


def at(row: float, column: float) -> tuple[float, float]:
    return NORTH_EDGE - (row + 0.5) * CELL, WEST_EDGE + (column + 0.5) * CELL


def fix(row: float, column: float, date: str = "2026-10-30 01:00", speed: float = 10.0) -> dict:
    lat, lon = at(row, column)
    return {"date": date, "lat": lat, "lon": lon, "speed": speed}


def way(tags: dict, points: list[tuple[float, float]]) -> dict:
    return {"type": "way", "tags": tags, "geometry": [{"lat": lat, "lon": lon} for lat, lon in points]}


COAST = way({"natural": "coastline"}, [(24.9, WEST - 0.1), (24.9, EAST + 0.1)])


def test_navigable_water_is_only_water_connected_to_the_sea():
    canal = way({"waterway": "canal"}, [(24.9, 55.0), (24.7, 55.0)])
    pond = way({"natural": "water"}, [(24.6, 54.6), (24.6, 54.62), (24.62, 54.62), (24.62, 54.6), (24.6, 54.6)])
    water = WaterMap(navigable_water([COAST, canal, pond]))
    assert water.km_to_water(25.2, 54.7) == 0
    assert water.km_to_water(24.8, 55.0) == 0
    assert water.km_to_water(24.61, 54.61) > 10
    assert water.km_to_water(24.8, 54.6) > 10


def test_a_multipolygon_lake_touching_the_sea_keeps_its_island():
    ring = [(24.9, 54.6), (24.9, 54.8), (24.7, 54.8), (24.7, 54.6), (24.9, 54.6)]
    island = [(24.82, 54.68), (24.82, 54.72), (24.78, 54.72), (24.78, 54.68), (24.82, 54.68)]
    half = len(ring) // 2
    members = [
        {"role": "outer", "geometry": [{"lat": lat, "lon": lon} for lat, lon in ring[:half + 1]]},
        {"role": "outer", "geometry": [{"lat": lat, "lon": lon} for lat, lon in ring[half:]]},
        {"role": "inner", "geometry": [{"lat": lat, "lon": lon} for lat, lon in island]},
    ]
    water = WaterMap(navigable_water([COAST, {"type": "relation", "tags": {"natural": "water"}, "members": members}]))
    assert water.km_to_water(24.75, 54.65) == 0
    assert water.km_to_water(24.8, 54.7) > 0


def test_waterways_to_draw_are_picked_by_name():
    named = way({"waterway": "canal", "name": "Dubai Canal"}, [(25.2, 55.2), (25.2, 55.3)])
    other = way({"waterway": "canal", "name": "Ganges"}, [(25.1, 55.2), (25.1, 55.3)])
    assert [item["name"] for item in named_waterways([named, other, COAST], ("Dubai Canal",))] == ["Dubai Canal"]


def test_the_water_grid_survives_saving(tmp_path):
    water = grid_map()
    water.save(tmp_path / "water.npz")
    loaded = WaterMap.load(tmp_path / "water.npz")
    assert (loaded.water == water.water).all()
    assert loaded.km_to_water(*at(150, 50)) == pytest.approx(water.km_to_water(*at(150, 50)))


def test_a_position_on_a_cell_corner_lands_in_the_same_cell_despite_floating_point_noise():
    water = grid_map()
    lat, lon = NORTH_EDGE - 50 * CELL, WEST_EDGE + 50 * CELL
    assert water._cell(lat, lon) == water._cell(lat + 1e-10, lon - 1e-10) == water._cell(lat - 1e-10, lon + 1e-10) == (50, 50)


def test_positions_are_kept_moved_or_removed_by_their_distance_from_water():
    water = grid_map()
    on_water, onshore, far = fix(50, 50), fix(103, 50), fix(170, 50)
    kept, removed = clean_positions({"v": [on_water, onshore, far]}, water)
    assert kept["v"][0] == on_water
    moved = kept["v"][1]
    assert moved["moved_to_water"] is True
    assert water.km_to_water(moved["lat"], moved["lon"]) == 0
    assert abs(moved["lat"] - onshore["lat"]) * 110.54 <= ROUNDING_KM
    assert [position["date"] for position in removed["v"]] == [far["date"]]
    assert removed["v"][0]["km"] > ROUNDING_KM


def test_a_ship_with_only_impossible_positions_has_nothing_left_to_draw():
    kept, removed = clean_positions({"v": [fix(170, 50)]}, grid_map())
    assert kept == {}
    assert list(removed) == ["v"]


def test_a_line_over_water_stays_straight():
    assert grid_map().line_to_next(fix(50, 50), fix(50, 80), 1, 40) == ([], False)


def test_a_line_across_land_follows_the_water():
    water = grid_map()
    points, jump = water.line_to_next(fix(50, 80), fix(50, 120), 2, 40)
    assert not jump
    assert points
    fractions = [point[0] for point in points]
    assert fractions == sorted(fractions)
    assert 0 < fractions[0] and fractions[-1] < 1
    assert all(water.km_to_water(lat, lon) == 0 for _, lat, lon in points)
    # It has to go around the end of the wall.
    assert min(lat for _, lat, _ in points) <= at(89.5, 0)[0]


def test_a_route_needing_an_impossible_speed_jumps_instead():
    assert grid_map().line_to_next(fix(50, 80), fix(50, 120), 1, 2) == ([], True)


def test_water_that_does_not_connect_jumps_instead():
    water = np.zeros((100, 100), dtype=bool)
    water[:, :40] = True
    water[:, 60:] = True
    grid = WaterMap(water, WEST_EDGE, NORTH_EDGE, CELL)
    assert grid.route(at(50, 10), at(50, 80)) is None
    assert grid.line_to_next(fix(50, 10), fix(50, 80), 1, 40) == ([], True)


class StubWater:
    def __init__(self, points=(), jump=False):
        self.result = (list(points), jump)
        self.calls = 0

    def line_to_next(self, before, after, hours, max_knots):
        self.calls += 1
        self.hours = hours
        return self.result


HOURS = {f"2026-10-30 0{hour}:00": hour for hour in range(9)}


def position(hour: int, lat: float = 25.0) -> dict:
    return {"date": f"2026-10-30 0{hour}:00", "lat": lat, "lon": 55.0, "speed": 8.0}


def test_estimated_rows_sit_between_real_ones_in_time_order():
    stub = StubWater([[0.25, 25.01, 55.01], [0.75, 25.02, 55.02]])
    rows, routed, jumps = movement_rows(3, [position(1), position(3, 25.1)], HOURS, stub)
    assert [row[1] for row in rows] == [1, 1.5, 2.5, 3]
    assert (routed, jumps) == (1, 0)
    assert stub.hours == 2
    assert all(row[0] == 3 for row in rows)


def test_a_jump_is_marked_on_the_position_before_it():
    rows, routed, jumps = movement_rows(0, [position(1), position(2, 25.1)], HOURS, StubWater(jump=True))
    assert rows[0][5:] == [1]
    assert len(rows[1]) == 5
    assert (routed, jumps) == (0, 1)


def test_no_line_is_worked_out_across_a_silence_or_for_a_ship_at_rest():
    stub = StubWater()
    movement_rows(0, [position(0), position(MAX_LINE_HOURS + 1, 25.1)], HOURS, stub)
    movement_rows(0, [position(1), position(2)], HOURS, stub)
    assert stub.calls == 0


def reasons_for(off_water):
    return ship_reasons({"name": "A", "flag": "PAN", "imo": "1", "mmsi": "2"}, [], 0, [], {"flags": [], "names": []}, 100, {}, {}, 2024, off_water)


def test_only_a_position_well_away_from_water_earns_a_note():
    assert reasons_for([{"km": 1.4}]) == []
    one = reasons_for([{"km": 5.2}])
    assert one[0]["kind"] == "off_water" and one[0]["level"] == "note"
    assert "a position 5 km from" in one[0]["text"]
    assert "2 positions up to 37 km from" in reasons_for([{"km": 18.7}, {"km": 36.7}])[0]["text"]


# The real files. These are what the replay draws, so every position and every line between them has to be on water.


def shipped_rows():
    if not (DERIVED / "ship_movement.json").exists() or not (DERIVED / "water_mask.npz").exists():
        pytest.skip("The movement data hasn't been built.")
    movement = json.loads((DERIVED / "ship_movement.json").read_text())
    by_ship: dict[int, list[list]] = {}
    for row in movement["fixes"]:
        by_ship.setdefault(row[0], []).append(row)
    return movement, by_ship, WaterMap.load(DERIVED / "water_mask.npz")


def test_every_shipped_position_is_on_water():
    movement, _, water = shipped_rows()
    off = [row for row in movement["fixes"] if water.km_to_water(row[2], row[3]) > 0]
    assert off == []


def test_no_shipped_line_crosses_land():
    movement, by_ship, water = shipped_rows()
    crossing = []
    for rows in by_ship.values():
        for before, after in itertools.pairwise(rows):
            if after[1] - before[1] > movement["max_line_hours"] or before[5:] == [1]:
                continue
            if water.deepest_km((before[2], before[3]), (after[2], after[3])) > LINE_CLIP_KM:
                crossing.append((before, after))
    assert crossing == []


def test_shipped_rows_are_in_time_order_for_every_ship():
    movement, by_ship, _ = shipped_rows()
    assert all(before[1] < after[1] for rows in by_ship.values() for before, after in itertools.pairwise(rows))
    assert {row[0] for row in movement["fixes"]} <= set(range(len(movement["ships"])))
    assert all(0 <= row[1] <= len(movement["hours"]) - 1 for row in movement["fixes"])
