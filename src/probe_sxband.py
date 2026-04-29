"""Probe SatNOGS Network for real S-band and X-band CubeSat observations.

For each S-band / X-band transmitter known to the cached SatNOGS DB
transmitters file, ask the Network API how many observations exist using
the transmitter UUID filter (more precise than the NORAD filter, since one
satellite often has multiple transmitters across different bands).

Uses gentle pacing + exponential backoff on 429 to avoid rate limit.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
TX = json.loads((RAW / "satnogs_transmitters.json").read_text())

URL = "https://network.satnogs.org/api/observations/"
HEADERS = {"User-Agent": "cubesat-link-budget-study/1.0 (academic)"}


def get_with_backoff(params: dict, max_attempts: int = 5) -> tuple[list, str]:
    delay = 5.0
    for i in range(max_attempts):
        r = requests.get(URL, params=params, headers=HEADERS, timeout=60)
        if r.status_code == 429:
            time.sleep(delay)
            delay *= 2
            continue
        r.raise_for_status()
        return r.json(), r.headers.get("Link", "")
    return [], ""


def band(f: float) -> str:
    if 1e9 <= f < 4e9:
        return "S"
    if 4e9 <= f < 12e9:
        return "X"
    return "other"


def main() -> None:
    sx = [t for t in TX
          if t.get("downlink_low") and 1e9 <= t["downlink_low"] < 12e9
          and t.get("alive")]
    print(f"S/X-band CubeSat transmitters in cached DB: {len(sx)}\n")

    summary = []
    for t in sx:
        b = band(t["downlink_low"])
        uuid = t["uuid"]
        params = {"transmitter_uuid": uuid, "status": "good"}
        time.sleep(2.0)  # be polite
        try:
            obs, link = get_with_backoff(params)
        except requests.RequestException as e:
            print(f"  {b} {t['norad_cat_id']:>6} {t['mode']:<6} ERROR {e}")
            continue
        n = len(obs)
        # crude estimate of total via Link rel="last"
        total_hint = ""
        if 'rel="last"' in link:
            for part in link.split(","):
                if 'rel="last"' in part:
                    total_hint = part.split(";")[0].strip().lstrip("<").rstrip(">")
        print(f"  {b} {t['norad_cat_id']:>6} {t['mode']:<6} "
              f"{t['downlink_low']/1e9:6.3f} GHz  good_obs(page1)={n}  "
              f"hint={total_hint[-60:] if total_hint else '-'}")
        summary.append({"band": b, "norad": t["norad_cat_id"], "mode": t["mode"],
                        "freq_ghz": t["downlink_low"] / 1e9,
                        "uuid": uuid, "good_obs_page1": n})

    # save list of UUIDs that have any observations
    with_obs = [s for s in summary if s["good_obs_page1"] > 0]
    (RAW / "sx_band_probe.json").write_text(json.dumps(summary, indent=2))
    print(f"\nTransmitters with at least 1 good obs on page 1: {len(with_obs)}")
    print("List saved to", RAW / "sx_band_probe.json")


if __name__ == "__main__":
    main()
