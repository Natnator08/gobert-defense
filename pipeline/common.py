"""Shared helpers: config, paths, cached HTTP (adapted from the park-access project)."""
from __future__ import annotations

import json
import time
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data_raw"
DATA = ROOT / "data"
SITE_DATA = ROOT / "site" / "data"

# Generic client name; no personal details are sent to services.
session = requests.Session()
session.headers["User-Agent"] = "gobert-defense-tracker/0.1 (open data research)"


def load_config() -> dict:
    return yaml.safe_load((ROOT / "config.yaml").read_text())


def log(msg: str) -> None:
    print(f"  · {msg}", flush=True)


def get(url: str, *, params=None, retries: int = 4, timeout: int = 60) -> requests.Response:
    for attempt in range(retries):
        try:
            r = session.get(url, params=params, timeout=timeout)
            if r.status_code in (429, 500, 502, 503, 504):
                raise requests.HTTPError(f"HTTP {r.status_code}")
            return r
        except (requests.RequestException, requests.HTTPError) as e:
            if attempt == retries - 1:
                raise
            wait = 3 * 2**attempt
            log(f"retrying in {wait}s after error: {e}")
            time.sleep(wait)
    raise AssertionError("unreachable")


def cached_json(url: str, cache: Path, *, params=None, refresh: bool = False) -> dict | None:
    """Fetch JSON once and keep it on disk. Returns None on 404 (e.g. a season ESPN doesn't have)."""
    if cache.exists() and not refresh:
        return json.loads(cache.read_text())
    r = get(url, params=params)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    data = r.json()
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(data))
    time.sleep(0.3)  # be polite to ESPN
    return data


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, separators=(",", ":"), allow_nan=False))


def season_label(season: int) -> str:
    """ESPN season 2024 -> '2023-24'."""
    return f"{season - 1}-{str(season)[-2:]}"
