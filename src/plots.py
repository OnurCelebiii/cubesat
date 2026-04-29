"""Generate figures for the link-budget study."""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "dataset.csv"
FIG = ROOT / "results" / "figures"
FIG.mkdir(parents=True, exist_ok=True)
sns.set_theme(style="whitegrid", context="talk")


def save(fig, name: str) -> None:
    path = FIG / name
    fig.savefig(path, dpi=140, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote {path}")


def main() -> None:
    df = pd.read_csv(DATA)
    band_order = [b for b in ["VHF", "UHF", "S", "X", "Other"] if b in df["band"].unique()]

    # 1. SNR distribution per band
    fig, ax = plt.subplots(figsize=(9, 6))
    sns.boxplot(data=df, x="band", y="snr_db", order=band_order,
                ax=ax, palette="viridis")
    sns.stripplot(data=df, x="band", y="snr_db", order=band_order,
                  ax=ax, color="black", size=1.5, alpha=0.25)
    ax.set_title("SNR per Frequency Band  (real SatNOGS observations)")
    ax.set_xlabel("Frequency band")
    ax.set_ylabel("Estimated SNR (dB)")
    save(fig, "01_snr_by_band.png")

    # 2. SNR vs altitude
    fig, ax = plt.subplots(figsize=(9, 6))
    sns.scatterplot(data=df, x="altitude_km", y="snr_db", hue="band",
                    hue_order=band_order, ax=ax, alpha=0.6, s=18)
    ax.set_title("SNR vs Orbital Altitude")
    ax.set_xlabel("Altitude (km)")
    ax.set_ylabel("SNR (dB)")
    save(fig, "02_snr_vs_altitude.png")

    # 3. SNR vs elevation
    fig, ax = plt.subplots(figsize=(9, 6))
    sns.scatterplot(data=df, x="elevation_deg", y="snr_db", hue="band",
                    hue_order=band_order, ax=ax, alpha=0.6, s=18)
    ax.set_title("SNR vs Maximum Elevation Angle")
    ax.set_xlabel("Elevation (deg)")
    ax.set_ylabel("SNR (dB)")
    save(fig, "03_snr_vs_elevation.png")

    # 4. SNR vs distance (FSPL driver)
    fig, ax = plt.subplots(figsize=(9, 6))
    sns.scatterplot(data=df, x="distance_km", y="snr_db", hue="band",
                    hue_order=band_order, ax=ax, alpha=0.6, s=18)
    ax.set_title("SNR vs Slant Range")
    ax.set_xlabel("Slant range (km)")
    ax.set_ylabel("SNR (dB)")
    save(fig, "04_snr_vs_distance.png")

    # 5. Rain attenuation by zone
    fig, ax = plt.subplots(figsize=(9, 6))
    sns.boxplot(data=df, x="rain_zone", y="rain_att_db",
                order=["tropical", "temperate", "polar"], ax=ax, palette="Blues")
    ax.set_title("Modelled Rain Attenuation by Climate Zone")
    ax.set_xlabel("Climate zone (latitude proxy)")
    ax.set_ylabel("Rain attenuation (dB)")
    save(fig, "05_rain_by_zone.png")

    # 6. Frequency distribution
    fig, ax = plt.subplots(figsize=(9, 6))
    sns.histplot(data=df, x="frequency_hz", hue="band", hue_order=band_order,
                 ax=ax, log_scale=True, multiple="stack", bins=40)
    ax.set_title("Observation Frequency Distribution")
    ax.set_xlabel("Frequency (Hz, log scale)")
    save(fig, "06_frequency_hist.png")

    # 7. FSPL vs frequency, coloured by altitude
    fig, ax = plt.subplots(figsize=(9, 6))
    sc = ax.scatter(df["frequency_hz"] / 1e9, df["fspl_db"],
                    c=df["altitude_km"], s=14, alpha=0.7, cmap="viridis")
    ax.set_xscale("log")
    plt.colorbar(sc, ax=ax, label="Altitude (km)")
    ax.set_title("Free-Space Path Loss vs Frequency")
    ax.set_xlabel("Frequency (GHz)")
    ax.set_ylabel("FSPL (dB)")
    save(fig, "07_fspl_vs_freq.png")

    # 8. Correlation heatmap
    cols = ["altitude_km", "elevation_deg", "distance_km", "frequency_hz",
            "fspl_db", "gas_att_db", "rain_att_db", "snr_db"]
    fig, ax = plt.subplots(figsize=(9, 7))
    sns.heatmap(df[cols].corr(), annot=True, fmt=".2f", cmap="RdBu_r",
                center=0, ax=ax, square=True, cbar_kws={"shrink": 0.8})
    ax.set_title("Pearson correlation matrix")
    save(fig, "08_correlation_heatmap.png")

    # 9. Success rate vs SNR (binned)
    df = df.copy()
    df["snr_bin"] = pd.cut(df["snr_db"], bins=10)
    rate = df.groupby("snr_bin", observed=True)["received_ok"].agg(["mean", "count"])
    rate = rate.reset_index()
    rate["snr_mid"] = rate["snr_bin"].apply(lambda b: b.mid).astype(float)
    fig, ax = plt.subplots(figsize=(9, 6))
    ax.plot(rate["snr_mid"], rate["mean"], marker="o")
    ax.set_xlabel("Estimated SNR (dB)")
    ax.set_ylabel("Empirical reception rate")
    ax.set_title("Reception success rate vs estimated SNR")
    save(fig, "09_success_vs_snr.png")

    print("All figures saved to", FIG)


if __name__ == "__main__":
    main()
