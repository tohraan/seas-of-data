"""Load and validate the files in contracts/, the only interface with the ML side, and the dashboard's own evidence."""
import base64
import csv
import hashlib
import io
import json
import os
from dataclasses import dataclass
from pathlib import Path

import jsonschema
import pandas as pd
from PIL import Image

CONTRACTS_DIR = Path(__file__).resolve().parent.parent / "contracts"
DERIVED_DIR = Path(__file__).resolve().parent / "derived"
BUOY_SPECS = Path(__file__).resolve().parent.parent / "cad" / "buoy" / "specs.json"

DETECTION_COLUMNS = [
    "id", "scene_id", "timestamp", "product", "confidence", "snr_z", "contrast_db", "land_distance_m",
    "length_m", "size_class", "persistence", "radar_class", "status", "review", "detector",
    "ais_matched", "dark", "mmsi", "port", "ais_source", "chip", "chip_context", "lon", "lat",
]
EVIDENCE_COLUMNS = [
    "detector_check", "yolo_confidence", "vv_contrast_db", "vh_contrast_db", "vh_confirmed",
    "radar_length_m", "axis_deg", "chip_vh", "passes_bright", "passes_measured", "fixed_likely",
]
# The same bands as ml/build_catalog.py.
SIZE_BANDS = [(30, "tiny"), (60, "small"), (120, "medium"), (200, "large")]

# contracts/ has no schema for port activity, so this mirrors contracts/README.md.
PORT_ACTIVITY_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "required": ["port", "date", "vessel_count", "activity_index"],
        "properties": {
            "port": {"type": "string"},
            "date": {"type": "string", "format": "date"},
            "scene_id": {"type": "string"},
            "vessel_count": {"type": "number", "minimum": 0},
            "uncertain_count": {"type": "number", "minimum": 0},
            "by_size": {"type": "object"},
            "basis": {"type": "string"},
            "activity_index": {"type": "number"},
        },
    },
}
EVIDENCE_REQUIRED = {"contract_sha256", "passes", "targets", "model", "settings", "source", "built_at"}


class ContractError(Exception):
    """A contract file exists but cannot be read or fails validation."""


@dataclass
class Loaded:
    frame: pd.DataFrame
    path: Path
    is_sample: bool


@dataclass
class Evidence:
    targets: pd.DataFrame
    passes: list[dict]
    model: dict
    settings: dict
    source: str
    built_at: str

    def pass_info(self, scene_id: str) -> dict | None:
        return next((item for item in self.passes if item["scene_id"] == scene_id), None)


def contracts_dir() -> Path:
    return Path(os.environ.get("SEAS_CONTRACTS_DIR") or CONTRACTS_DIR)


def _derived_dir() -> Path:
    return Path(os.environ.get("SEAS_DERIVED_DIR") or DERIVED_DIR)


def _resolve(directory: Path, real: str, sample: str) -> tuple[Path, bool]:
    real_path = directory / real
    if real_path.exists():
        return real_path, False
    return directory / sample, True


def _read_json(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise ContractError(f"{path.name}: {exc}") from exc


def _read_optional_json(path: Path) -> dict | list | None:
    """Files that add to the dashboard but aren't needed for it to run. None if missing or unreadable."""
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _validate(document, schema: dict, name: str) -> None:
    validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
    errors = sorted(validator.iter_errors(document), key=lambda e: list(map(str, e.absolute_path)))
    if errors:
        first = errors[0]
        where = "/".join(map(str, first.absolute_path)) or "(root)"
        raise ContractError(f"{name}: {len(errors)} validation error(s). First at {where}: {first.message}")


def size_class(length) -> str | None:
    if pd.isna(length):
        return None
    return next((name for top, name in SIZE_BANDS if length < top), "very_large")


def _status_from_flag(dark) -> str:
    """Older files only have the dark flag. A missing flag means nothing was checked."""
    if dark is True:
        return "no_ais_match"
    return "matched" if dark is False else "not_checked"


def load_detections(directory: Path | None = None) -> Loaded:
    directory = directory or contracts_dir()
    path, is_sample = _resolve(directory, "detections.geojson", "sample_detections.geojson")
    document = _read_json(path)
    schema = _read_json(directory / "detections.schema.json")
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
        properties = dict(feature["properties"])
        properties.setdefault("status", _status_from_flag(properties.get("dark")))
        properties.setdefault("radar_class", "ship")
        properties.setdefault("review", "unreviewed")
        properties.setdefault("persistence", 1)
        properties.setdefault("size_class", size_class(properties.get("length_m")))
        rows.append({**properties, "lon": lon, "lat": lat})

    frame = pd.DataFrame(rows).reindex(columns=DETECTION_COLUMNS)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, format="ISO8601")
    # Stays an object column: None means not checked, and must never turn into False.
    frame["dark"] = frame["dark"].astype(object)
    return Loaded(frame, path, is_sample)


def load_port_activity(directory: Path | None = None) -> Loaded:
    directory = directory or contracts_dir()
    path, is_sample = _resolve(directory, "port_activity.json", "sample_port_activity.json")
    document = _read_json(path)
    _validate(document, PORT_ACTIVITY_SCHEMA, path.name)

    columns = ["port", "date", "vessel_count", "uncertain_count", "by_size", "activity_index"]
    frame = pd.DataFrame(document).reindex(columns=columns)
    frame["date"] = pd.to_datetime(frame["date"])
    return Loaded(frame.sort_values(["port", "date"]), path, is_sample)


def load_manifest(directory: Path | None = None) -> dict | None:
    return _read_optional_json((directory or contracts_dir()) / "manifest.json")


def load_gulf_metrics(directory: Path | None = None) -> dict | None:
    return _read_optional_json((directory or contracts_dir()) / "metrics_gulf.json")


def load_coverage(directory: Path | None = None) -> dict | None:
    return _read_optional_json((directory or contracts_dir()) / "coverage.json")


def load_labels(directory: Path | None = None) -> pd.DataFrame:
    path = (directory or contracts_dir()) / "labels.csv"
    try:
        with path.open(newline="") as handle:
            return pd.DataFrame(list(csv.DictReader(handle)))
    except OSError:
        return pd.DataFrame(columns=["id", "verdict", "reviewer", "size_class", "port"])


def load_model_metrics() -> dict | None:
    return _read_optional_json(_derived_dir() / "model_metrics.json")


def load_buoy_specs() -> dict | None:
    return _read_optional_json(BUOY_SPECS)


def load_evidence(contract_path: Path) -> tuple[Evidence | None, str]:
    """Returns (evidence, state), where state is ok, missing, stale (built from a different contract) or invalid."""
    document = _read_optional_json(_derived_dir() / "evidence.json")
    if document is None:
        return None, "missing"
    if not isinstance(document, dict) or not EVIDENCE_REQUIRED <= set(document):
        return None, "invalid"
    if document["contract_sha256"] != hashlib.sha256(contract_path.read_bytes()).hexdigest():
        return None, "stale"
    targets = pd.DataFrame(document["targets"])
    targets = targets.rename(columns={"detector": "detector_check"})
    return Evidence(
        targets, document["passes"], document["model"], document["settings"], document["source"], document["built_at"],
    ), "ok"


def attach_evidence(detections: pd.DataFrame, evidence: Evidence | None) -> pd.DataFrame:
    """Add the second-opinion measurements to the contract's detections. Rows the pipeline didn't measure stay empty."""
    if evidence is None:
        return detections.reindex(columns=[*detections.columns, *EVIDENCE_COLUMNS])
    columns = [column for column in EVIDENCE_COLUMNS if column in evidence.targets.columns]
    measured = evidence.targets.loc[~evidence.targets["yolo_only"], ["id", *columns]]
    merged = detections.merge(measured, on="id", how="left")
    return merged.reindex(columns=[*detections.columns, *EVIDENCE_COLUMNS])


def resolve_chip(relative: object, directory: Path | None = None) -> Path | None:
    """The chip's path, only if it really is a file inside the contracts folder."""
    if not isinstance(relative, str) or not relative:
        return None
    base = (directory or contracts_dir()).resolve()
    path = (base / relative).resolve()
    return path if path.is_relative_to(base) and path.is_file() else None


def thumbnail_uri(relative: object, size: int = 72, directory: Path | None = None) -> str | None:
    """A small copy of a chip for table rows, so a long table doesn't send megabytes to the browser."""
    path = resolve_chip(relative, directory)
    if path is None:
        return None
    with Image.open(path) as image:
        small = image.convert("L").resize((size, size), Image.LANCZOS)
    buffer = io.BytesIO()
    small.save(buffer, "JPEG", quality=78)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()


def radar_image_uri(relative: str) -> str | None:
    path = _derived_dir() / relative
    try:
        return "data:image/webp;base64," + base64.b64encode(path.read_bytes()).decode()
    except OSError:
        return None


def summarise(detections: pd.DataFrame) -> dict:
    classes = detections["radar_class"]
    return {
        "total": len(detections),
        "ship": int((classes == "ship").sum()),
        "uncertain": int((classes == "uncertain").sum()),
        "likely_fixed": int((classes == "likely_fixed").sum()),
    }
