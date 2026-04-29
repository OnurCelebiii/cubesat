"""Fetch SatNOGS Network observations for the S-band CubeSat transmitters
listed in the cached SatNOGS DB.

Uses the transmitter UUID filter (more precise than the NORAD filter, since
each satellite usually has multiple transmitters across different bands)
plus exponential backoff on HTTP 429.

Output: data/raw/satnogs_sband_observations.json
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
URL = "https://network.satnogs.org/api/observations/"
HEADERS = {"User-Agent": "cubesat-link-budget-study/1.0 (academic)"}


def fetch_url(url: str, params: dict | None, max_attempts: int = 6) -> tuple[list, dict]:
    delay = 5.0
    for _ in range(max_attempts):
        r = requests.get(url, params=params, headers=HEADERS, timeout=60)
        if r.status_code == 429:
            time.sleep(delay)
            delay *= 2
            continue
        r.raise_for_status()
        return r.json(), r.headers
    return [], {}


def next_url(link_header: str) -> str | None:
    for part in link_header.split(","):
        if 'rel="next"' in part:
            return part.split(";")[0].strip().lstrip("<").rstrip(">")
    return None


def paginate_uuid(uuid: str, status: str, max_pages: int = 8) -> list:
    out: list = []
    url: str | None = URL
    params: dict | None = {"transmitter_uuid": uuid, "status": status}
    pages = 0
    while url and pages < max_pages:
        time.sleep(2.5)
        try:
            batch, headers = fetch_url(url, params)
        except requests.RequestException as e:
            print(f"    page {pages + 1}: ERROR {e}")
            break
        if not batch:
            break
        out.extend(batch)
        url = next_url(headers.get("Link", ""))
        params = None  # next URL already carries params
        pages += 1
    return out


def main() -> None:
    tx = json.loads((RAW / "satnogs_transmitters.json").read_text())
    sband = [t for t in tx
             if t.get("downlink_low") and 1e9 <= t["downlink_low"] < 4e9
             and t.get("alive")]
    print(f"S-band transmitters to query: {len(sband)}")

    all_obs: list = []
    for t in sband:
        uuid = t["uuid"]
        nid = t["norad_cat_id"]
        f_ghz = t["downlink_low"] / 1e9
        print(f"  NORAD {nid:>6}  {t['mode']:<6} {f_ghz:.3f} GHz  uuid={uuid[:10]}…")
        for status in ("good", "bad"):
            obs = paginate_uuid(uuid, status)
            print(f"    status={status:<4}  fetched={len(obs)}")
            all_obs.extend(obs)

    out = RAW / "satnogs_sband_observations.json"
    out.write_text(json.dumps(all_obs, indent=2))
    print(f"\nWrote {len(all_obs)} S-band observations -> {out}")


if __name__ == "__main__":
    main()
