"""The buoy's calculated numbers: they must balance, stay reproducible and fail loudly when the design doesn't work."""
import copy
import importlib.util
import json
import math
from pathlib import Path

import pytest

BUOY = Path(__file__).resolve().parents[2] / "cad" / "buoy"
spec = importlib.util.spec_from_file_location("calc_buoy", BUOY / "calc_buoy.py")
calc_buoy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(calc_buoy)


@pytest.fixture
def geometry():
    return json.loads((BUOY / "geometry.json").read_text())


def test_published_numbers_match_a_fresh_calculation(geometry):
    assert json.loads((BUOY / "specs.json").read_text()) == json.loads(json.dumps(calc_buoy.calculate(geometry)))


def test_mass_budget_balances_the_water_displaced(geometry):
    specs = calc_buoy.calculate(geometry)
    assert sum(row["kg"] for row in specs["mass_budget"]) == pytest.approx(specs["total_mass_kg"], abs=0.5)
    assert specs["displaced_volume_m3"] * calc_buoy.ASSUMPTIONS["seawater_density_kg_m3"] == pytest.approx(specs["total_mass_kg"], abs=1)


def test_stability_adds_up_and_matches_a_hand_calculation(geometry):
    specs = calc_buoy.calculate(geometry)
    assert specs["metacentric_height_m"] > 0
    assert (specs["kb_mm"] + specs["bm_mm"] - specs["kg_mm"]) / 1000 == pytest.approx(specs["metacentric_height_m"], abs=0.01)
    by_hand_bm_mm = math.pi * 900**4 / 4 / (specs["displaced_volume_m3"] * 1e9)
    assert specs["bm_mm"] == pytest.approx(by_hand_bm_mm, rel=0.01)


def test_ballast_sets_the_waterline_above_the_unballasted_one(geometry):
    specs = calc_buoy.calculate(geometry)
    assert specs["keel_ballast_kg"] > 0
    assert specs["waterline_without_ballast_mm"] < specs["waterline_mm"]


def test_a_buoy_too_heavy_for_its_waterline_is_rejected(geometry):
    assumptions = {**calc_buoy.ASSUMPTIONS, "water_depth_m": 200}
    with pytest.raises(ValueError, match="too heavy"):
        calc_buoy.calculate(geometry, assumptions)


def test_an_unstable_loading_is_rejected(geometry):
    top_heavy = copy.deepcopy(geometry)
    top_heavy["parts"]["Hatch"]["centre_z_mm"] = 30000
    with pytest.raises(ValueError, match="unstable"):
        calc_buoy.calculate(top_heavy)


def test_range_formulas():
    assert calc_buoy.radio_horizon_km(4, 16) == pytest.approx(24.72)
    assert calc_buoy.optical_horizon_km(4, 16) == pytest.approx(21.42)


def test_longer_chain_raises_load_and_cuts_ballast(geometry):
    shallow = calc_buoy.calculate(geometry, {**calc_buoy.ASSUMPTIONS, "water_depth_m": 15})
    deep = calc_buoy.calculate(geometry, {**calc_buoy.ASSUMPTIONS, "water_depth_m": 35})
    assert deep["keel_ballast_kg"] < shallow["keel_ballast_kg"]


def test_datasheet_says_it_is_design_only_and_lists_assumptions(geometry):
    sheet = calc_buoy.datasheet(calc_buoy.calculate(geometry))
    assert "Not built or tested" in sheet
    assert "water depth m" in sheet
    assert "{" not in sheet


def test_published_datasheet_is_current(geometry):
    assert (BUOY / "DATASHEET.md").read_text() == calc_buoy.datasheet(calc_buoy.calculate(geometry))
