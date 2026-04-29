"""Fetch real public CubeSat data from CelesTrak and SatNOGS.

Sources:
  - CelesTrak GP API:        https://celestrak.org/NORAD/elements/gp.php
  - SatNOGS DB transmitters: https://db.satnogs.org/api/transmitters/
  - SatNOGS Network obs:     https://network.satnogs.org/api/observations/

Outputs JSON files into data/raw/ for downstream processing.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import requests

RAW = Path(__file__).resolve().parents[1] / "data" / "raw"
RAW.mkdir(parents=True, exist_ok=True)

CELESTRAK_CUBESAT = "https://celestrak.org/NORAD/elements/gp.php?GROUP=cubesat&FORMAT=json"
SATNOGS_DB_TX = "https://db.satnogs.org/api/transmitters/"
SATNOGS_NET_OBS = "https://network.satnogs.org/api/observations/"

HEADERS = {"User-Agent": "cubesat-link-budget-study/1.0 (academic)"}
TIMEOUT = 60


def get_json(url: str, params: dict | None = None) -> list | dict:
    r = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def paginate(url: str, params: dict | None = None, max_pages: int = 80) -> list:
    """Walk SatNOGS pagination via Link: <...>; rel="next" header."""
    out: list = []
    page_url: str | None = url
    page_params = dict(params or {})
    pages = 0
    while page_url and pages < max_pages:
        r = requests.get(page_url, params=page_params, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        batch = r.json()
        if not isinstance(batch, list):
            break
        out.extend(batch)
        link = r.headers.get("Link", "")
        nxt = None
        for part in link.split(","):
            if 'rel="next"' in part:
                nxt = part.split(";")[0].strip().lstrip("<").rstrip(">")
                break
        page_url = nxt
        page_params = None  # next URL already carries the params
        pages += 1
        time.sleep(0.4)
    return out


def fetch_cubesat_tles() -> list:
    print("[1/3] Fetching CubeSat TLE/GP data from CelesTrak...")
    data = get_json(CELESTRAK_CUBESAT)
    print(f"      got {len(data)} CubeSat orbital records")
    (RAW / "celestrak_cubesats.json").write_text(json.dumps(data, indent=2))
    return data


def fetch_transmitters(norad_ids: list[int]) -> list:
    print("[2/3] Fetching SatNOGS DB transmitters...")
    all_tx = get_json(SATNOGS_DB_TX)
    norad_set = set(norad_ids)
    filtered = [t for t in all_tx if t.get("norad_cat_id") in norad_set and t.get("alive")]
    print(f"      total transmitters={len(all_tx)}, matched CubeSat alive={len(filtered)}")
    (RAW / "satnogs_transmitters.json").write_text(json.dumps(filtered, indent=2))
    return filtered


def fetch_observations(norad_ids: list[int], per_sat_limit_pages: int = 3) -> list:
    """Fetch recent vetted observations for each CubeSat NORAD ID."""
    print("[3/3] Fetching SatNOGS Network observations (per satellite)...")
    out: list = []
    for i, nid in enumerate(norad_ids, 1):
        try:
            batch = paginate(
                SATNOGS_NET_OBS,
                params={"satellite__norad_cat_id": nid, "status": "good"},
                max_pages=per_sat_limit_pages,
            )
            batch_bad = paginate(
                SATNOGS_NET_OBS,
                params={"satellite__norad_cat_id": nid, "status": "bad"},
                max_pages=1,
            )
            obs = batch + batch_bad
            out.extend(obs)
            print(f"      [{i:>3}/{len(norad_ids)}] NORAD {nid}: {len(obs)} obs (cum={len(out)})")
        except requests.RequestException as e:
            print(f"      WARN NORAD {nid}: {e}")
        if len(out) > 8000:
            print("      reached collection cap, stopping")
            break
    (RAW / "satnogs_observations.json").write_text(json.dumps(out, indent=2))
    return out


def main() -> None:
    tles = fetch_cubesat_tles()
    norad_ids = sorted({int(t["NORAD_CAT_ID"]) for t in tles if t.get("NORAD_CAT_ID")})
    fetch_transmitters(norad_ids)
    fetch_observations(norad_ids)
    print("Done. Files in", RAW)


if __name__ == "__main__":
    main()
