"""Join CelesTrak + SatNOGS sources into a single observation-level dataset
and compute link-budget quantities used in the statistical study.

Per observation we derive:
  * orbital altitude        (from CelesTrak MEAN_MOTION via Kepler's 3rd law)
  * frequency band          (UHF / VHF / S-band / other, from observation_frequency)
  * elevation (deg)         (max_altitude reported by SatNOGS)
  * slant range (km)        (spherical-Earth geometry, given alt + elevation)
  * free space path loss    (Friis: FSPL = 20 log10(4 pi d / lambda))
  * gas attenuation         (ITU-R P.676 simplified, elevation + freq dependent)
  * rain attenuation proxy  (ITU rain-zone proxy via |station_lat|)
  * link margin / SNR proxy (typical CubeSat tx power + GS antenna assumptions)
  * outcome label           (vetted_status / status from SatNOGS, "good"/"bad")

Outputs data/dataset.csv.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "dataset.csv"

# Physical constants
MU_EARTH = 398600.4418        # km^3/s^2
R_EARTH = 6378.137            # km
C = 2.99792458e8              # m/s

# Assumed CubeSat link parameters (typical values used as constants per band).
# These are documented in README so reviewers can see exactly what is fixed
# and what is varied.  Variation across observations comes from real fields:
#   altitude (TLE), frequency (transmitter), elevation (max_altitude), latitude.
TX_POWER_DBM = 30.0           # 1 W typical CubeSat transmitter
TX_ANT_GAIN_DBI = 2.0         # dipole / patch
RX_ANT_GAIN_DBI = {           # typical SatNOGS ground station antennas
    "VHF": 11.0,
    "UHF": 14.0,
    "S": 22.0,
    "X": 30.0,
    "Other": 10.0,
}
SYS_NOISE_TEMP_K = 290.0
BANDWIDTH_HZ = 9600.0
BOLTZMANN_DBW_HZ_K = -228.6  # 10*log10(k)

# polarization + cable loss budget (dB)
MISC_LOSS_DB = 3.0


def kepler_altitude_from_mean_motion(mean_motion_rev_per_day: float) -> float:
    """Convert TLE mean motion (rev/day) to circular-equivalent altitude (km)."""
    n_rad_s = mean_motion_rev_per_day * 2.0 * math.pi / 86400.0
    a_km = (MU_EARTH / (n_rad_s ** 2)) ** (1.0 / 3.0)
    return a_km - R_EARTH


def altitude_from_tle_line2(tle2: str) -> float | None:
    """Mean motion is columns 53-63 (1-indexed) of TLE line 2."""
    if not tle2 or len(tle2) < 63:
        return None
    try:
        mm = float(tle2[52:63].strip())
    except ValueError:
        return None
    if not (1.0 < mm < 20.0):
        return None
    return kepler_altitude_from_mean_motion(mm)


def freq_band(freq_hz: float | None) -> str:
    if not freq_hz or freq_hz <= 0:
        return "Unknown"
    f = float(freq_hz)
    if 30e6 <= f < 300e6:
        return "VHF"
    if 300e6 <= f < 1e9:
        return "UHF"
    if 1e9 <= f < 4e9:
        return "S"
    if 4e9 <= f < 12e9:
        return "X"
    return "Other"


def slant_range_km(altitude_km: float, elevation_deg: float) -> float:
    """Spherical-Earth slant range from a ground station at sea level.

    d = -R sin(el) + sqrt((R sin el)^2 + 2 R h + h^2)
    """
    el = math.radians(max(elevation_deg, 0.1))
    Re = R_EARTH
    h = altitude_km
    s = -Re * math.sin(el) + math.sqrt((Re * math.sin(el)) ** 2 + 2 * Re * h + h * h)
    return s


def fspl_db(distance_km: float, freq_hz: float) -> float:
    if distance_km <= 0 or not freq_hz:
        return float("nan")
    lam = C / freq_hz
    return 20.0 * math.log10(4.0 * math.pi * distance_km * 1000.0 / lam)


def gas_attenuation_db(elevation_deg: float, freq_hz: float) -> float:
    """ITU-R P.676 simplified zenith attenuation scaled by 1/sin(el).

    Uses a small-frequency-grid lookup (oxygen + water-vapour, mid-latitude).
    Adequate for an academic study; real ITU-R needs full line-by-line model.
    """
    f_ghz = freq_hz / 1e9
    # Approximate one-way zenith specific attenuation A_zenith [dB] mid-latitude:
    # values calibrated against ITU-R P.676-12 figures (clear sky).
    table = [
        (0.1, 0.04), (0.4, 0.05), (1.0, 0.06), (2.4, 0.08), (4.0, 0.10),
        (8.0, 0.20), (12.0, 0.45), (20.0, 1.5), (30.0, 0.6),
    ]
    fs = [t[0] for t in table]
    az = [t[1] for t in table]
    a_zen = float(np.interp(f_ghz, fs, az))
    el = math.radians(max(elevation_deg, 1.0))
    return a_zen / math.sin(el)


def rain_attenuation_db(lat_deg: float, freq_hz: float, elevation_deg: float) -> float:
    """Crude ITU-R P.837/P.838-style rain attenuation proxy.

    R0.01 (mm/h) varies with climate.  Use latitude as a proxy for ITU rain zone:
    tropical (|lat|<23) -> 60 mm/h, temperate (23-50) -> 30, polar (>50) -> 10.
    Specific attenuation k*R^a with band-dependent (k,a) coefficients.
    """
    if not freq_hz:
        return 0.0
    f_ghz = freq_hz / 1e9
    abs_lat = abs(lat_deg)
    if abs_lat < 23.0:
        r001 = 60.0
    elif abs_lat < 50.0:
        r001 = 30.0
    else:
        r001 = 10.0
    # ITU-R P.838-3 vertical-pol coefficients (subset)
    table = [
        (1.0, 0.0000259, 0.9691),
        (4.0, 0.000591, 1.075),
        (10.0, 0.0188, 1.217),
        (15.0, 0.0367, 1.154),
        (20.0, 0.0691, 1.065),
        (30.0, 0.167, 0.972),
    ]
    fs = [t[0] for t in table]
    ks = [t[1] for t in table]
    as_ = [t[2] for t in table]
    k = float(np.interp(f_ghz, fs, ks))
    a = float(np.interp(f_ghz, fs, as_))
    gamma = k * (r001 ** a)  # dB/km specific attenuation
    # Effective slant path length through 5 km rain height
    el = math.radians(max(elevation_deg, 5.0))
    L = 5.0 / math.sin(el)
    return gamma * L


def compute_snr_db(row) -> float:
    """Friis-equation link budget producing receiver SNR (dB).

    SNR = EIRP + Gr - FSPL - L_atm - L_rain - L_misc - (kTB)
    """
    band = row["band"]
    if band == "Unknown" or row["fspl_db"] != row["fspl_db"]:  # NaN check
        return float("nan")
    eirp = TX_POWER_DBM + TX_ANT_GAIN_DBI - 30.0  # convert to dBW
    gr = RX_ANT_GAIN_DBI.get(band, RX_ANT_GAIN_DBI["Other"])
    n0 = BOLTZMANN_DBW_HZ_K + 10.0 * math.log10(SYS_NOISE_TEMP_K) + 10.0 * math.log10(BANDWIDTH_HZ)
    return (
        eirp + gr
        - row["fspl_db"]
        - row["gas_att_db"]
        - row["rain_att_db"]
        - MISC_LOSS_DB
        - n0
    )


def main() -> None:
    tles = json.loads((RAW / "celestrak_cubesats.json").read_text())
    txs = json.loads((RAW / "satnogs_transmitters.json").read_text())
    obs = json.loads((RAW / "satnogs_observations.json").read_text())
    print(f"Loaded: tles={len(tles)} transmitters={len(txs)} observations={len(obs)}")

    # ---- altitude lookup (NORAD -> altitude_km) ----
    alt_lookup: dict[int, float] = {}
    name_lookup: dict[int, str] = {}
    for t in tles:
        nid = int(t.get("NORAD_CAT_ID", 0))
        mm = t.get("MEAN_MOTION")
        if not nid or mm is None:
            continue
        try:
            alt_lookup[nid] = kepler_altitude_from_mean_motion(float(mm))
            name_lookup[nid] = t.get("OBJECT_NAME", "")
        except (TypeError, ValueError):
            continue

    # ---- assemble observation-level dataframe ----
    # Prefer per-observation TLE for altitude (covers sats not in CelesTrak group);
    # fall back to CelesTrak lookup if the embedded TLE is unparseable.
    rows = []
    for o in obs:
        nid = o.get("norad_cat_id")
        alt = altitude_from_tle_line2(o.get("tle2", ""))
        if alt is None:
            alt = alt_lookup.get(nid)
        if alt is None:
            continue
        elev = o.get("max_altitude")
        freq = o.get("observation_frequency") or o.get("transmitter_downlink_low")
        lat = o.get("station_lat")
        status = (o.get("vetted_status") or o.get("status") or "").lower()
        if elev is None or freq is None or lat is None:
            continue
        if status not in {"good", "bad", "failed"}:
            continue
        rows.append(
            {
                "obs_id": o["id"],
                "norad_id": nid,
                "sat_name": name_lookup.get(nid, ""),
                "altitude_km": alt,
                "elevation_deg": float(elev),
                "frequency_hz": float(freq),
                "station_lat": float(lat),
                "station_lng": float(o.get("station_lng", 0.0) or 0.0),
                "status": status,
            }
        )

    df = pd.DataFrame(rows)
    if df.empty:
        raise SystemExit("No usable observations after join — check fetch step.")

    df["band"] = df["frequency_hz"].apply(freq_band)
    df = df[df["band"] != "Unknown"].copy()

    df["distance_km"] = [
        slant_range_km(a, e) for a, e in zip(df["altitude_km"], df["elevation_deg"])
    ]
    df["fspl_db"] = [fspl_db(d, f) for d, f in zip(df["distance_km"], df["frequency_hz"])]
    df["gas_att_db"] = [
        gas_attenuation_db(e, f) for e, f in zip(df["elevation_deg"], df["frequency_hz"])
    ]
    df["rain_att_db"] = [
        rain_attenuation_db(lat, f, e)
        for lat, f, e in zip(df["station_lat"], df["frequency_hz"], df["elevation_deg"])
    ]
    df["snr_db"] = df.apply(compute_snr_db, axis=1)
    df["received_ok"] = (df["status"] == "good").astype(int)
    df["rain_zone"] = pd.cut(
        df["station_lat"].abs(), bins=[-0.1, 23, 50, 91],
        labels=["tropical", "temperate", "polar"],
    )

    df = df.dropna(subset=["snr_db"])
    df.to_csv(OUT, index=False)
    print(f"Wrote {OUT}  rows={len(df)}  bands={df['band'].value_counts().to_dict()}")


if __name__ == "__main__":
    main()
