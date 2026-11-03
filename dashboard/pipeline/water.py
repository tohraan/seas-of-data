"""Where a boat can really be: navigable water from OpenStreetMap, and the position checks that use it.

Fishing Watch rounds positions to 0.01 degrees, so a ship in a canal or at a quay can appear up to about 750 m away, on land.
Those are moved to the nearest water, which is where the ship was. Anything further can't be explained by rounding, so it's
treated as a wrong position rather than drawn in the desert.
"""
import heapq
import itertools
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

WEST, SOUTH, EAST, NORTH = 54.35, 24.45, 55.40, 25.40  # a little wider than the study area, so the coast closes around it
RES = 0.0005  # degrees, about 55 m
SEA_SEED = (25.2, 54.7)  # lat, lon of open water
ROUNDING_KM = 0.8  # half the diagonal of a 0.01 degree square is about 0.75 km, plus half a mask cell
LINE_CLIP_KM = 0.2  # a straight line may clip this far over land: about a pixel at the default zoom
LINE_WATERWAYS = {"canal", "river", "dock", "boatyard"}
LINE_WIDTH_CELLS = 3  # mapped centre lines, about 150 m wide
SIMPLIFY_STRIDE = 5
POSITION_DECIMALS = 4  # about 10 m, finer than a cell of the grid
KM_PER_DEGREE_LAT = 110.54
KM_PER_DEGREE_LON = 111.32
KNOT_KM_H = 1.852


def _rings(relation: dict, role: str) -> list[list[tuple[float, float]]]:
    """A multipolygon's member ways, chained into closed rings by their touching ends."""
    pieces = [[(point["lon"], point["lat"]) for point in member["geometry"]] for member in relation.get("members", []) if member.get("role") == role and member.get("geometry")]
    rings = []
    while pieces:
        ring = pieces.pop()
        grew = True
        while grew and ring[0] != ring[-1]:
            grew = False
            for index, piece in enumerate(pieces):
                if piece[0] == ring[-1]:
                    ring += piece[1:]
                elif piece[-1] == ring[-1]:
                    ring += piece[-2::-1]
                else:
                    continue
                pieces.pop(index)
                grew = True
                break
        rings.append(ring)
    return rings


def navigable_water(elements: list[dict]) -> np.ndarray:
    """Water connected to the sea, as a grid with row 0 at the north edge. Ponds and desert lakes aren't navigable from it.

    The sea is found by filling outwards from open water up to the coastlines, because OpenStreetMap maps the coast as lines.
    """
    width, height = round((EAST - WEST) / RES), round((NORTH - SOUTH) / RES)

    def pixel(lon: float, lat: float) -> tuple[float, float]:
        return (lon - WEST) / RES, (NORTH - lat) / RES

    coast_image, water_image = Image.new("1", (width, height), 0), Image.new("1", (width, height), 0)
    coast, water = ImageDraw.Draw(coast_image), ImageDraw.Draw(water_image)
    holes = []
    for element in elements:
        tags = element.get("tags", {})
        if element["type"] == "relation":
            for ring in _rings(element, "outer"):
                if len(ring) >= 4:
                    water.polygon([pixel(*point) for point in ring], fill=1)
            holes += [[pixel(*point) for point in ring] for ring in _rings(element, "inner") if len(ring) >= 4]
            continue
        geometry = element.get("geometry") or []
        points = [pixel(point["lon"], point["lat"]) for point in geometry]
        if len(points) < 2:
            continue
        if tags.get("natural") == "coastline":
            coast.line(points, fill=1, width=1)
        elif len(points) >= 4 and geometry[0] == geometry[-1]:
            water.polygon(points, fill=1)
        elif tags.get("waterway") in LINE_WATERWAYS:
            water.line(points, fill=1, width=LINE_WIDTH_CELLS)
    for hole in holes:
        water.polygon(hole, fill=0)

    coast_cells = np.array(coast_image, dtype=bool)
    regions, _ = ndimage.label(~coast_cells)
    seed_column, seed_row = pixel(SEA_SEED[1], SEA_SEED[0])
    sea = regions == regions[int(seed_row), int(seed_column)]
    all_water = sea | coast_cells | np.array(water_image, dtype=bool)
    connected, _ = ndimage.label(all_water, structure=np.ones((3, 3), dtype=bool))
    return connected == connected[int(seed_row), int(seed_column)]


def named_waterways(elements: list[dict], names: tuple[str, ...]) -> list[dict]:
    """Centre lines to draw, because the base map leaves narrow canals out at the zoom the replay opens at."""
    found = []
    for element in elements:
        tags = element.get("tags", {})
        name = tags.get("name:en") or tags.get("name")
        if element["type"] == "way" and name in names and tags.get("waterway"):
            found.append({"name": name, "path": [[round(point["lon"], 4), round(point["lat"], 4)] for point in element["geometry"]]})
    return found


class WaterMap:
    def __init__(self, water: np.ndarray, west: float = WEST, north: float = NORTH, res: float = RES):
        self.water = water
        self.west, self.north, self.res = west, north, res
        latitude = north - water.shape[0] * res / 2
        self.cell_km = (res * KM_PER_DEGREE_LAT, res * KM_PER_DEGREE_LON * math.cos(math.radians(latitude)))
        self._km, self._nearest = ndimage.distance_transform_edt(~water, sampling=self.cell_km, return_indices=True)

    @classmethod
    def load(cls, path: Path) -> "WaterMap":
        with np.load(path) as saved:
            shape = tuple(saved["shape"])
            water = np.unpackbits(saved["bits"])[: shape[0] * shape[1]].reshape(shape).astype(bool)
            return cls(water, float(saved["west"]), float(saved["north"]), float(saved["res"]))

    def save(self, path: Path) -> None:
        np.savez_compressed(path, bits=np.packbits(self.water), shape=self.water.shape, west=self.west, north=self.north, res=self.res)

    def _cell(self, lat: float, lon: float) -> tuple[int, int]:
        rows, columns = self.water.shape
        # Fishing Watch's 0.01 degree grid falls exactly on cell corners, so rounding stops floating-point noise choosing the cell.
        row, column = int(round((self.north - lat) / self.res, 6)), int(round((lon - self.west) / self.res, 6))
        return min(rows - 1, max(0, row)), min(columns - 1, max(0, column))

    def _point(self, row: int, column: int) -> tuple[float, float]:
        return round(self.north - (row + 0.5) * self.res, POSITION_DECIMALS), round(self.west + (column + 0.5) * self.res, POSITION_DECIMALS)

    def km_to_water(self, lat: float, lon: float) -> float:
        return float(self._km[self._cell(lat, lon)])

    def nearest_water(self, lat: float, lon: float) -> tuple[float, float]:
        row, column = self._cell(lat, lon)
        return self._point(int(self._nearest[0][row, column]), int(self._nearest[1][row, column]))

    def _line(self, start: tuple[int, int], end: tuple[int, int]) -> tuple[np.ndarray, np.ndarray]:
        steps = max(abs(start[0] - end[0]), abs(start[1] - end[1])) + 1
        return np.linspace(start[0], end[0], steps).round().astype(int), np.linspace(start[1], end[1], steps).round().astype(int)

    def deepest_km(self, start: tuple[float, float], end: tuple[float, float]) -> float:
        """How far from water a straight line between two positions gets."""
        rows, columns = self._line(self._cell(*start), self._cell(*end))
        return float(self._km[rows, columns].max())

    def _simplify(self, cells: list[tuple[int, int]]) -> list[tuple[int, int]]:
        """Straighten a path that follows the grid, wherever a straight line stays on water."""
        cells = cells[::SIMPLIFY_STRIDE] + ([cells[-1]] if (len(cells) - 1) % SIMPLIFY_STRIDE else [])
        kept = [cells[0]]
        index = 0
        while index < len(cells) - 1:
            for far in range(len(cells) - 1, index, -1):
                if far == index + 1 or self.water[self._line(cells[index], cells[far])].all():
                    kept.append(cells[far])
                    index = far
                    break
        return kept

    def route(self, start: tuple[float, float], end: tuple[float, float]) -> list[tuple[float, float]] | None:
        """The shortest way over water between two positions, or None if water doesn't connect them."""
        source, target = self._cell(*start), self._cell(*end)
        if not self.water[source] or not self.water[target]:
            return None
        down, across = self.cell_km
        moves = [(row, column, math.hypot(row * down, column * across)) for row in (-1, 0, 1) for column in (-1, 0, 1) if row or column]

        def remaining(cell: tuple[int, int]) -> float:
            return math.hypot((cell[0] - target[0]) * down, (cell[1] - target[1]) * across)

        rows, columns = self.water.shape
        best = {source: 0.0}
        previous: dict[tuple[int, int], tuple[int, int]] = {}
        frontier = [(remaining(source), source)]
        while frontier:
            _, cell = heapq.heappop(frontier)
            if cell == target:
                path = [cell]
                while path[-1] != source:
                    path.append(previous[path[-1]])
                return [self._point(*step) for step in self._simplify(path[::-1])]
            for row, column, cost in moves:
                neighbour = (cell[0] + row, cell[1] + column)
                if not (0 <= neighbour[0] < rows and 0 <= neighbour[1] < columns) or not self.water[neighbour]:
                    continue
                distance = best[cell] + cost
                if distance < best.get(neighbour, math.inf):
                    best[neighbour] = distance
                    previous[neighbour] = cell
                    heapq.heappush(frontier, (distance + remaining(neighbour), neighbour))
        return None

    def line_to_next(self, before: dict, after: dict, hours: float, max_knots: float) -> tuple[list[list[float]], bool]:
        """How to draw the time between two positions: estimated points as [fraction, lat, lon], and whether to jump instead.

        A straight line that stays on water needs nothing. One that crosses land follows the shortest way over water, unless
        the ship would have needed an impossible speed to sail it, and then no line is drawn at all.
        """
        start, end = (before["lat"], before["lon"]), (after["lat"], after["lon"])
        if self.deepest_km(start, end) <= LINE_CLIP_KM:
            return [], False
        path = self.route(start, end)
        if path is None:
            return [], True
        lengths = [math.hypot((a[0] - b[0]) * KM_PER_DEGREE_LAT, (a[1] - b[1]) * self.cell_km[1] / self.res) for a, b in itertools.pairwise(path)]
        total = sum(lengths)
        if total / hours / KNOT_KM_H > max_knots:
            return [], True
        points = []
        sailed = 0.0
        for point, length in zip(path[1:-1], lengths, strict=False):
            sailed += length
            points.append([round(sailed / total, 4), point[0], point[1]])
        return points, False


def clean_positions(fixes_by_vessel: dict[str, list[dict]], water: WaterMap) -> tuple[dict[str, list[dict]], dict[str, list[dict]]]:
    """Fixes on water, moving those that rounding put on land. Also returns the impossible ones, removed, by vessel."""
    kept_by_vessel, removed_by_vessel = {}, {}
    for vessel_id, fixes in fixes_by_vessel.items():
        kept, removed = [], []
        for fix in fixes:
            # Check exactly what gets written out, because a tiny difference can land in another cell of the grid.
            lat, lon = round(fix["lat"], POSITION_DECIMALS), round(fix["lon"], POSITION_DECIMALS)
            km = water.km_to_water(lat, lon)
            if km == 0:
                kept.append({**fix, "lat": lat, "lon": lon})
            elif km <= ROUNDING_KM:
                lat, lon = water.nearest_water(lat, lon)
                kept.append({**fix, "lat": round(lat, POSITION_DECIMALS), "lon": round(lon, POSITION_DECIMALS), "moved_to_water": True})
            else:
                removed.append({"date": fix["date"], "lat": lat, "lon": lon, "km": round(km, 1), "speed": fix.get("speed")})
        if kept:
            kept_by_vessel[vessel_id] = kept
        if removed:
            removed_by_vessel[vessel_id] = removed
    return kept_by_vessel, removed_by_vessel
