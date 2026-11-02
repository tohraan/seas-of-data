"""Load and validate the files in contracts/, the only interface with the ML side."""
import json
from dataclasses import dataclass
from pathlib import Path

import jsonschema
import pandas as pd

CONTRACTS_DIR = Path(__file__).resolve().parent.parent / "contracts"

DETECTION_COLUMNS = [
    "id", "scene_id", "timestamp", "confidence", "length_m",
    "ais_matched", "dark", "mmsi", "port", "lon", "lat",
]

# contracts/ has no schema for port activity, so this mirrors contracts/README.md.
PORT_ACTIVITY_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "required": ["port", "date", "vessel_count", "berth_occupancy_pct", "activity_index"],
        "properties": {
            "port": {"type": "string"},
            "date": {"type": "string", "format": "date"},
            "vessel_count": {"type": "number", "minimum": 0},
            "berth_occupancy_pct": {"type": "number", "minimum": 0, "maximum": 100},
            "activity_index": {"type": "number"},
        },
    },
}


class ContractError(Exception):
    """A contract file exists but cannot be read or fails validation."""


@dataclass
class Loaded:
    frame: pd.DataFrame
    path: Path
    is_sample: bool


def _resolve(contracts_dir: Path, real: str, sample: str) -> tuple[Path, bool]:
    real_path = contracts_dir / real
    if real_path.exists():
        return real_path, False
    return contracts_dir / sample, True


def _read_json(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise ContractError(f"{path.name}: {exc}") from exc


def _validate(document, schema: dict, name: str) -> None:
    validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
    errors = sorted(validator.iter_errors(document), key=lambda e: list(map(str, e.absolute_path)))
    if errors:
        first = errors[0]
        where = "/".join(map(str, first.absolute_path)) or "(root)"
        raise ContractError(f"{name}: {len(errors)} validation error(s). First at {where}: {first.message}")


def load_detections(contracts_dir: Path = CONTRACTS_DIR) -> Loaded:
    path, is_sample = _resolve(contracts_dir, "detections.geojson", "sample_detections.geojson")
    document = _read_json(path)
    schema = _read_json(contracts_dir / "detections.schema.json")
    _validate(document, schema, path.name)

    rows = []
    for feature in document["features"]:
        lon, lat = feature["geometry"]["coordinates"]
        # The schema does not bound coordinates; this also catches swapped [lat, lon].
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            raise ContractError(
                f"{path.name}: detection {feature['properties']['id']} has "
                f"out-of-range coordinates [{lon}, {lat}]; expected [lon, lat]"
            )
        rows.append({**feature["properties"], "lon": lon, "lat": lat})

    frame = pd.DataFrame(rows).reindex(columns=DETECTION_COLUMNS)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, format="ISO8601")
    frame["dark"] = frame["dark"].astype(bool)
    return Loaded(frame, path, is_sample)


def load_port_activity(contracts_dir: Path = CONTRACTS_DIR) -> Loaded:
    path, is_sample = _resolve(contracts_dir, "port_activity.json", "sample_port_activity.json")
    document = _read_json(path)
    _validate(document, PORT_ACTIVITY_SCHEMA, path.name)

    frame = pd.DataFrame(document, columns=list(PORT_ACTIVITY_SCHEMA["items"]["required"]))
    frame["date"] = pd.to_datetime(frame["date"])
    return Loaded(frame.sort_values(["port", "date"]), path, is_sample)


def summarise(detections: pd.DataFrame) -> dict:
    total = len(detections)
    dark = int(detections["dark"].sum())
    return {"total": total, "dark": dark, "pct_dark": 100 * dark / total if total else 0.0}
