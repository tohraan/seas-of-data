"""Client for the Global Fishing Watch API. The token stays in ml/.env and is never logged, cached or written out."""
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://gateway.api.globalfishingwatch.org/v3"
ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = ROOT / "ml" / ".env"
CACHE_DIR = ROOT / "data" / "gfw_cache"
# Cloudflare in front of the API rejects Python's default client name.
USER_AGENT = "seas-of-data-dashboard/0.1"
RETRY_STATUS = {429, 502, 503, 524}
RETRIES = 5
RETRY_WAIT_S = 30
PAGE_SIZE = 1000
CACHE_HOURS = 12
IDENTITY_DATASET = "public-global-vessel-identity:latest"


class GfwError(RuntimeError):
    pass


def read_token(path: Path = ENV_FILE) -> str:
    try:
        for line in path.read_text().splitlines():
            if line.startswith("GFW_TOKEN="):
                token = line.split("=", 1)[1].strip()
                if token:
                    return token
    except OSError:
        pass
    raise SystemExit(f"Put GFW_TOKEN=... in {path} first.")


class Client:
    def __init__(self, token: str, cache_dir: Path = CACHE_DIR, refresh: bool = False, pause_s: float = 0.25):
        self._token = token
        self.cache_dir = cache_dir
        self.refresh = refresh
        self.pause_s = pause_s
        self.calls = 0
        cache_dir.mkdir(parents=True, exist_ok=True)

    def _scrub(self, text: str) -> str:
        return text.replace(self._token, "<token>")

    def request(self, path: str, body: dict | None = None, params: dict | None = None) -> dict:
        query = urllib.parse.urlencode(params or {})
        key = hashlib.sha256(json.dumps([path, query, body], sort_keys=True).encode()).hexdigest()
        cached = self.cache_dir / f"{key}.json"
        if not self.refresh and cached.exists() and time.time() - cached.stat().st_mtime < CACHE_HOURS * 3600:
            return json.loads(cached.read_text())

        url = f"{API}{path}" + (f"?{query}" if query else "")
        data = json.dumps(body).encode() if body is not None else None
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
        for attempt in range(RETRIES):
            time.sleep(self.pause_s)
            self.calls += 1
            try:
                with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers), timeout=180) as response:
                    result = json.load(response)
                cached.write_text(json.dumps(result))
                return result
            except urllib.error.HTTPError as error:
                detail = self._scrub(error.read().decode("utf-8", "ignore")[:400])
                if error.code not in RETRY_STATUS or attempt == RETRIES - 1:
                    raise GfwError(f"{path}: HTTP {error.code}: {detail}") from None
            except (urllib.error.URLError, TimeoutError) as error:
                if attempt == RETRIES - 1:
                    raise GfwError(f"{path}: {type(error).__name__}") from None
            time.sleep(RETRY_WAIT_S)
        raise GfwError(f"{path}: gave up")

    def report(self, dataset: str, start: str, end: str, area: dict, temporal: str = "HOURLY", matched: bool | None = None) -> list[dict]:
        """A 4Wings report, one row per vessel and cell. The API runs one report per user at a time, so these stay sequential."""
        params = {
            "spatial-resolution": "HIGH",
            "temporal-resolution": temporal,
            "datasets[0]": dataset,
            "date-range": f"{start},{end}",
            "format": "JSON",
            "group-by": "VESSEL_ID",
        }
        if matched is not None:
            params["filters[0]"] = f"matched='{str(matched).lower()}'"
        rows: list[dict] = []
        for block in self.request("/4wings/report", {"geojson": area}, params).get("entries", []):
            for values in block.values():
                rows.extend(values or [])
        return rows

    def events(self, dataset: str, start: str, end: str, area: dict | None = None, vessels: list[str] | None = None) -> list[dict]:
        body: dict = {"datasets": [dataset], "startDate": start, "endDate": end}
        if area:
            body["geometry"] = area
        if vessels:
            body["vessels"] = vessels
        entries: list[dict] = []
        offset = 0
        while True:
            page = self.request("/events", body, {"limit": PAGE_SIZE, "offset": offset})
            entries.extend(page.get("entries", []))
            offset = page.get("nextOffset")
            if not offset:
                return entries

    def identities(self, vessel_ids: list[str]) -> list[dict]:
        params: dict[str, str] = {"datasets[0]": IDENTITY_DATASET}
        for index, vessel_id in enumerate(vessel_ids):
            params[f"ids[{index}]"] = vessel_id
        return self.request("/vessels", None, params).get("entries", [])


    def search_by_imo(self, imo: str) -> list[dict]:
        """Every identity a hull has used, which a lookup by vessel ID doesn't show."""
        params = {"where": f"imo='{imo}'", "datasets[0]": IDENTITY_DATASET, "limit": 25}
        return self.request("/vessels/search", None, params).get("entries", [])


def fetch_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read().decode("latin-1")
