"""Measurements taken from radar pixels. Only numpy and scipy, so this can be tested without satellite data."""
import base64
import io
import math

import numpy as np
from PIL import Image
from scipy import ndimage as ndi

MATCH_GATE_M = 250  # detector positions closer than this count as the same target
PEAK_RADIUS_PX = 4  # about 40 m at 10 m pixels: covers small position differences between passes
RING_INNER_PX = 16
RING_OUTER_PX = 32
CHIP_PX = 96
MIN_SHAPE_PIXELS = 6
MIN_ELONGATION = 1.5


def distance_m(lon1, lat1, lon2, lat2) -> float:
    dx = (lon2 - lon1) * 111320 * math.cos(math.radians((lat1 + lat2) / 2))
    dy = (lat2 - lat1) * 110540
    return math.hypot(dx, dy)


def match_detections(first: list[tuple[float, float]], second: list[tuple[float, float]], gate_m: float = MATCH_GATE_M) -> list[tuple[int, int]]:
    """Pair detections one-to-one, closest pairs first. Each input is a list of (lon, lat)."""
    candidates = []
    for i, (lon1, lat1) in enumerate(first):
        for j, (lon2, lat2) in enumerate(second):
            if abs(lat1 - lat2) * 110540 > gate_m:
                continue
            distance = distance_m(lon1, lat1, lon2, lat2)
            if distance <= gate_m:
                candidates.append((distance, i, j))
    pairs, used_first, used_second = [], set(), set()
    for _, i, j in sorted(candidates):
        if i not in used_first and j not in used_second:
            pairs.append((i, j))
            used_first.add(i)
            used_second.add(j)
    return pairs


def _ring_mask() -> np.ndarray:
    span = np.arange(-RING_OUTER_PX, RING_OUTER_PX + 1)
    rows, cols = np.meshgrid(span, span, indexing="ij")
    radius = np.hypot(rows, cols)
    return (radius >= RING_INNER_PX) & (radius <= RING_OUTER_PX)


_RING = _ring_mask()


def _to_db(pixels: np.ndarray) -> np.ndarray:
    return 20 * np.log10(np.maximum(pixels.astype("float32"), 1.0))


def local_contrast(pixels: np.ndarray, row: float, col: float) -> float:
    """Brightest point near (row, col), in dB above the median of the ring around it. NaN if it can't be measured."""
    r, c = round(row), round(col)
    if r < RING_OUTER_PX or c < RING_OUTER_PX or r + RING_OUTER_PX >= pixels.shape[0] or c + RING_OUTER_PX >= pixels.shape[1]:
        return float("nan")
    crop = pixels[r - RING_OUTER_PX : r + RING_OUTER_PX + 1, c - RING_OUTER_PX : c + RING_OUTER_PX + 1]
    ring = crop[_RING]
    ring = ring[ring > 0]
    if ring.size < _RING.sum() / 2:  # mostly no-data: the edge of the scene
        return float("nan")
    core = pixels[r - PEAK_RADIUS_PX : r + PEAK_RADIUS_PX + 1, c - PEAK_RADIUS_PX : c + PEAK_RADIUS_PX + 1]
    return float(_to_db(core).max() - np.median(_to_db(ring)))


def ship_shape(pixels: np.ndarray, row: float, col: float, half_px: int = 32) -> tuple[float, float, float, float] | None:
    """Fit the bright blob at (row, col). Returns (length_px, elongation, axis_row, axis_col), or None if there's no clear blob."""
    r, c = round(row), round(col)
    r0, c0 = max(0, r - half_px), max(0, c - half_px)
    crop = pixels[r0 : r + half_px + 1, c0 : c + half_px + 1]
    if crop.size == 0 or crop.max() == 0:
        return None
    db = _to_db(crop)
    background = float(np.median(db[crop > 0]))
    near_r0, near_c0 = max(0, r - r0 - PEAK_RADIUS_PX), max(0, c - c0 - PEAK_RADIUS_PX)
    near = db[near_r0 : r - r0 + PEAK_RADIUS_PX + 1, near_c0 : c - c0 + PEAK_RADIUS_PX + 1]
    if near.size == 0:
        return None
    peak_at = np.unravel_index(int(near.argmax()), near.shape)
    peak_r, peak_c = peak_at[0] + near_r0, peak_at[1] + near_c0
    peak = float(db[peak_r, peak_c])
    threshold = background + max(6.0, 0.5 * (peak - background))
    # Diagonal neighbours count as connected, or a thin ship lying at 45 degrees falls apart into single pixels.
    labels, _ = ndi.label(db > threshold, structure=np.ones((3, 3)))
    label = labels[peak_r, peak_c]
    if label == 0:
        return None
    rows, cols = np.nonzero(labels == label)
    if rows.size < MIN_SHAPE_PIXELS:
        return None
    covariance = np.cov(np.vstack([rows, cols]).astype("float64"))
    values, vectors = np.linalg.eigh(covariance)
    minor, major = max(float(values[0]), 1e-6), max(float(values[1]), 1e-6)
    length = math.sqrt(12 * major)  # a uniform bar of length L has variance L^2 / 12 along its axis
    return length, math.sqrt(major / minor), float(vectors[0, 1]), float(vectors[1, 1])


def bearing_deg(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Compass direction of the line between two points, from 0 up to 180: a hull axis has no front or back."""
    east = (lon2 - lon1) * math.cos(math.radians((lat1 + lat2) / 2))
    north = lat2 - lat1
    return math.degrees(math.atan2(east, north)) % 180


def chip_data_uri(pixels: np.ndarray, row: float, col: float, stretch: tuple[float, float], size: int = CHIP_PX) -> str | None:
    """A small radar image centred on the target, as a data URI the dashboard can show directly."""
    half = size // 2
    r, c = round(row), round(col)
    if r < 0 or c < 0 or r >= pixels.shape[0] or c >= pixels.shape[1]:
        return None
    canvas = np.zeros((size, size), dtype=pixels.dtype)
    r0, c0 = max(0, r - half), max(0, c - half)
    crop = pixels[r0 : r + half, c0 : c + half]
    canvas[r0 - (r - half) : r0 - (r - half) + crop.shape[0], c0 - (c - half) : c0 - (c - half) + crop.shape[1]] = crop
    low, high = stretch
    image = np.clip((_to_db(canvas) - low) / (high - low) * 255, 0, 255).astype("uint8")
    buffer = io.BytesIO()
    Image.fromarray(image).save(buffer, "JPEG", quality=72)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()


def downsample_amplitude(pixels: np.ndarray, factor: int) -> np.ndarray:
    height, width = pixels.shape[0] // factor, pixels.shape[1] // factor
    rows = []
    for index in range(height):  # row by row, so the whole scene is never held as floats
        block = pixels[index * factor : (index + 1) * factor, : width * factor].astype("float32")
        rows.append(block.reshape(factor, width, factor).mean(axis=(0, 2)))
    return np.stack(rows)
