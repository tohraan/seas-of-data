import base64
import math

import numpy as np
import pytest

from evidence_math import (
    CHIP_PX,
    bearing_deg,
    chip_data_uri,
    distance_m,
    downsample_amplitude,
    local_contrast,
    match_detections,
    ship_shape,
)


def sea(size=200, level=30, seed=1):
    rng = np.random.default_rng(seed)
    return rng.rayleigh(level / 1.25, (size, size)).clip(1, 65000).astype("uint16")


def add_ship(pixels, row, col, length, angle_deg, brightness=3000):
    """Paint a bright bar. angle_deg is measured from the row axis towards the column axis."""
    angle = math.radians(angle_deg)
    for t in np.linspace(-length / 2, length / 2, length * 4):
        r, c = row + t * math.cos(angle), col + t * math.sin(angle)
        pixels[round(r), round(c)] = brightness
    return pixels


def test_distance_is_about_111_km_per_degree_of_latitude():
    assert distance_m(55, 25, 55, 26) == pytest.approx(110540)
    assert distance_m(55, 25, 55.001, 25) == pytest.approx(100.9, abs=0.5)


def test_matching_pairs_closest_first_one_to_one_and_respects_the_gate():
    first = [(55.0, 25.0), (55.002, 25.0), (56.0, 25.0)]
    second = [(55.0005, 25.0), (55.0012, 25.0)]
    assert sorted(match_detections(first, second, gate_m=250)) == [(0, 0), (1, 1)]
    assert match_detections([(55.0, 25.0)], [(55.01, 25.0)], gate_m=250) == []
    assert match_detections([], second) == []


def test_contrast_of_a_ship_beats_open_sea():
    pixels = sea()
    open_sea = local_contrast(pixels, 100, 100)
    ship = local_contrast(add_ship(pixels, 100, 100, 12, 30), 100, 100)
    assert ship > open_sea + 20
    assert ship == pytest.approx(20 * math.log10(3000) - 20 * math.log10(np.median(sea()[60:140, 60:140])), abs=2)


def test_contrast_is_not_measurable_at_the_scene_edge_or_on_no_data():
    pixels = sea()
    assert math.isnan(local_contrast(pixels, 5, 100))
    assert math.isnan(local_contrast(np.zeros((200, 200), "uint16"), 100, 100))


@pytest.mark.parametrize("angle", [0, 30, 60, 90, 135])
def test_ship_shape_recovers_direction_and_length(angle):
    pixels = add_ship(sea(), 100, 100, 24, angle)
    length, elongation, axis_row, axis_col = ship_shape(pixels, 100, 100)
    assert length == pytest.approx(24, abs=3)
    assert elongation > 3
    measured = math.degrees(math.atan2(axis_col, axis_row)) % 180
    difference = abs(measured - angle % 180)
    assert min(difference, 180 - difference) < 5


def test_ship_shape_returns_none_when_there_is_no_blob():
    assert ship_shape(sea(), 100, 100) is None


def test_bearing_has_no_front_or_back():
    assert bearing_deg(55, 25, 55, 25.1) == pytest.approx(0)
    assert bearing_deg(55, 25, 55.1, 25) == pytest.approx(90)
    assert bearing_deg(55.1, 25, 55, 25) == pytest.approx(90)
    assert bearing_deg(55, 25, 55.1, 25.1) == pytest.approx(bearing_deg(55.1, 25.1, 55, 25))


def test_chip_is_a_valid_image_of_the_right_size_even_at_the_edge():
    from io import BytesIO

    from PIL import Image

    for row, col in [(100, 100), (3, 3), (198, 198)]:
        uri = chip_data_uri(sea(), row, col, (0, 80))
        assert uri.startswith("data:image/jpeg;base64,")
        image = Image.open(BytesIO(base64.b64decode(uri.split(",", 1)[1])))
        assert image.size == (CHIP_PX, CHIP_PX)
    assert chip_data_uri(sea(), -1, 5, (0, 80)) is None


def test_downsample_averages_blocks_and_drops_the_remainder():
    pixels = np.array([[1, 3, 5, 7, 9], [1, 3, 5, 7, 9]], "uint16")
    assert downsample_amplitude(pixels, 2).tolist() == [[2.0, 6.0]]
