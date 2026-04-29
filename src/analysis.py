"""Statistical analysis of the CubeSat link-budget dataset.

Tests the five project hypotheses using ten statistical methods:

  1. Descriptive statistics (per band, overall)
  2. Shapiro-Wilk normality test
  3. Pearson + Spearman correlation
  4. One-way ANOVA across frequency bands
  5. Kruskal-Wallis non-parametric ANOVA
  6. Mann-Whitney U pairwise post-hoc with Bonferroni correction
  7. Simple linear regression (altitude->SNR, elevation->SNR, distance->SNR)
  8. Multiple linear regression (altitude + elevation + freq->SNR)
  9. Two-sample hypothesis tests (rainy vs dry, high vs low elevation)
 10. 95% confidence intervals for SNR per band

Hypotheses
  H1  bands differ in SNR
  H2  altitude correlates negatively with SNR
  H3  rain attenuation lowers SNR significantly
  H4  elevation correlates positively with SNR
  H5  altitude + elevation + frequency jointly explain SNR (R^2)

Writes results/tables/*.csv and prints a summary report.
"""
from __future__ import annotations

from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "dataset.csv"
TBL = ROOT / "results" / "tables"
TBL.mkdir(parents=True, exist_ok=True)
REPORT = ROOT / "results" / "report.txt"


def section(title: str) -> str:
    bar = "=" * 78
    return f"\n{bar}\n{title}\n{bar}\n"


def fmt_p(p: float) -> str:
    return f"{p:.4g}" + ("  ***" if p < 0.001 else "  **" if p < 0.01 else "  *" if p < 0.05 else "")


def main() -> None:
    df = pd.read_csv(DATA)
    out: list[str] = []
    out.append(section("CubeSat Link Budget – Statistical Analysis on Real SatNOGS Data"))
    out.append(f"Observations: {len(df)}")
    out.append(f"Bands:        {df['band'].value_counts().to_dict()}")
    out.append(f"Stations lat range: [{df['station_lat'].min():.1f}, {df['station_lat'].max():.1f}]")
    out.append(f"Altitude range (km): [{df['altitude_km'].min():.0f}, {df['altitude_km'].max():.0f}]")

    # ---------- 1. Descriptive ----------
    out.append(section("1) Descriptive statistics"))
    desc = (
        df.groupby("band")["snr_db"]
        .agg(["count", "mean", "median", "std", "min", "max"])
        .round(2)
    )
    out.append(desc.to_string())
    desc.to_csv(TBL / "01_descriptive.csv")

    overall = df["snr_db"].agg(["count", "mean", "median", "std", "min", "max"]).round(2)
    out.append("\nOverall SNR:\n" + overall.to_string())

    # ---------- 2. Shapiro-Wilk normality ----------
    out.append(section("2) Shapiro-Wilk normality test (per band, n<=5000)"))
    rows = []
    for b, g in df.groupby("band"):
        s = g["snr_db"].dropna().sample(min(len(g), 5000), random_state=0)
        if len(s) < 3:
            continue
        W, p = stats.shapiro(s)
        rows.append({"band": b, "n": len(s), "W": round(W, 4), "p_value": p,
                     "normal_alpha_0.05": p > 0.05})
    norm_df = pd.DataFrame(rows)
    out.append(norm_df.to_string(index=False))
    norm_df.to_csv(TBL / "02_shapiro.csv", index=False)

    # ---------- 3. Pearson + Spearman ----------
    out.append(section("3) Pearson and Spearman correlations against SNR"))
    rows = []
    for col in ["altitude_km", "elevation_deg", "distance_km", "frequency_hz",
                "gas_att_db", "rain_att_db"]:
        x = df[col].astype(float)
        y = df["snr_db"].astype(float)
        m = x.notna() & y.notna()
        if m.sum() < 10:
            continue
        r, pr = stats.pearsonr(x[m], y[m])
        rho, prho = stats.spearmanr(x[m], y[m])
        rows.append({"variable": col, "n": int(m.sum()),
                     "pearson_r": round(r, 4), "pearson_p": pr,
                     "spearman_rho": round(rho, 4), "spearman_p": prho})
    cor_df = pd.DataFrame(rows)
    out.append(cor_df.to_string(index=False))
    cor_df.to_csv(TBL / "03_correlations.csv", index=False)

    # ---------- 4. One-way ANOVA ----------
    out.append(section("4) One-way ANOVA — SNR by frequency band (H1)"))
    groups = [g["snr_db"].dropna().values for _, g in df.groupby("band")]
    F, p = stats.f_oneway(*groups)
    out.append(f"F = {F:.3f},  p = {fmt_p(p)}")
    pd.DataFrame([{"F": F, "p_value": p}]).to_csv(TBL / "04_anova.csv", index=False)

    # ---------- 5. Kruskal-Wallis ----------
    out.append(section("5) Kruskal-Wallis non-parametric ANOVA"))
    H, p = stats.kruskal(*groups)
    out.append(f"H = {H:.3f},  p = {fmt_p(p)}")
    pd.DataFrame([{"H": H, "p_value": p}]).to_csv(TBL / "05_kruskal.csv", index=False)

    # ---------- 6. Pairwise Mann-Whitney with Bonferroni ----------
    out.append(section("6) Mann-Whitney U pairwise (Bonferroni-corrected)"))
    bands = sorted(df["band"].unique())
    pairs = list(combinations(bands, 2))
    rows = []
    for a, b in pairs:
        xa = df.loc[df.band == a, "snr_db"].dropna().values
        xb = df.loc[df.band == b, "snr_db"].dropna().values
        if len(xa) < 5 or len(xb) < 5:
            continue
        U, p = stats.mannwhitneyu(xa, xb, alternative="two-sided")
        rows.append({"band_A": a, "band_B": b, "n_A": len(xa), "n_B": len(xb),
                     "U": U, "p_raw": p, "p_bonf": min(1.0, p * len(pairs))})
    mw = pd.DataFrame(rows)
    out.append(mw.to_string(index=False))
    mw.to_csv(TBL / "06_mannwhitney.csv", index=False)

    # ---------- 7. Simple linear regressions ----------
    out.append(section("7) Simple linear regressions on SNR"))
    rows = []
    for col in ["altitude_km", "elevation_deg", "distance_km"]:
        x = df[col].astype(float)
        y = df["snr_db"].astype(float)
        m = x.notna() & y.notna()
        slope, intercept, r, p, se = stats.linregress(x[m], y[m])
        rows.append({"x": col, "slope": slope, "intercept": intercept,
                     "r": r, "r2": r ** 2, "p_value": p, "stderr": se,
                     "n": int(m.sum())})
    lin_df = pd.DataFrame(rows)
    out.append(lin_df.round(4).to_string(index=False))
    lin_df.to_csv(TBL / "07_simple_regression.csv", index=False)

    # ---------- 8. Multiple linear regression ----------
    out.append(section("8) Multiple linear regression: SNR ~ altitude + elevation + freq + band-dummies"))
    X = df[["altitude_km", "elevation_deg", "frequency_hz"]].copy()
    X["frequency_ghz"] = X.pop("frequency_hz") / 1e9
    band_dum = pd.get_dummies(df["band"], prefix="band", drop_first=True).astype(float)
    X = pd.concat([X.astype(float), band_dum], axis=1)
    X = sm.add_constant(X)
    y = df["snr_db"].astype(float)
    model = sm.OLS(y, X, missing="drop").fit()
    out.append(str(model.summary()))
    coef_df = pd.DataFrame({
        "coef": model.params, "std_err": model.bse,
        "t": model.tvalues, "p_value": model.pvalues,
    })
    coef_df.to_csv(TBL / "08_multiple_regression.csv")
    pd.DataFrame([{
        "n": int(model.nobs), "r2": model.rsquared, "adj_r2": model.rsquared_adj,
        "F": model.fvalue, "p_value": model.f_pvalue,
    }]).to_csv(TBL / "08_multiple_regression_summary.csv", index=False)

    # ---------- 9. Two-sample hypothesis tests ----------
    out.append(section("9) Two-sample hypothesis tests"))
    rows = []
    # 9a Rainy vs dry (proxy: tropical vs polar latitudes)
    rainy = df.loc[df["rain_zone"] == "tropical", "snr_db"].dropna()
    dry = df.loc[df["rain_zone"] == "polar", "snr_db"].dropna()
    if len(rainy) > 5 and len(dry) > 5:
        t, p = stats.ttest_ind(rainy, dry, equal_var=False)
        rows.append({"test": "tropical vs polar (rain proxy)", "n_A": len(rainy),
                     "n_B": len(dry), "stat": t, "p_value": p})
    # 9b high vs low elevation
    median_el = df["elevation_deg"].median()
    hi = df.loc[df["elevation_deg"] >= median_el, "snr_db"].dropna()
    lo = df.loc[df["elevation_deg"] < median_el, "snr_db"].dropna()
    t, p = stats.ttest_ind(hi, lo, equal_var=False)
    rows.append({"test": f"elevation>={median_el:.1f}° vs <{median_el:.1f}°",
                 "n_A": len(hi), "n_B": len(lo), "stat": t, "p_value": p})
    # 9c received_ok proxy — does measured SNR predict observation success?
    ok = df.loc[df["received_ok"] == 1, "snr_db"].dropna()
    bad = df.loc[df["received_ok"] == 0, "snr_db"].dropna()
    if len(ok) > 5 and len(bad) > 5:
        t, p = stats.ttest_ind(ok, bad, equal_var=False)
        rows.append({"test": "successful obs vs failed obs (real label)",
                     "n_A": len(ok), "n_B": len(bad), "stat": t, "p_value": p})
    h_df = pd.DataFrame(rows)
    out.append(h_df.to_string(index=False))
    h_df.to_csv(TBL / "09_hypothesis_tests.csv", index=False)

    # ---------- 10. 95 % CI per band ----------
    out.append(section("10) 95% confidence intervals for mean SNR per band"))
    rows = []
    for b, g in df.groupby("band"):
        x = g["snr_db"].dropna().values
        if len(x) < 2:
            continue
        m = x.mean()
        se = stats.sem(x)
        ci = stats.t.interval(0.95, len(x) - 1, loc=m, scale=se)
        rows.append({"band": b, "n": len(x), "mean": m, "ci_low": ci[0], "ci_high": ci[1]})
    ci_df = pd.DataFrame(rows).round(3)
    out.append(ci_df.to_string(index=False))
    ci_df.to_csv(TBL / "10_confidence_intervals.csv", index=False)

    # ---------- Hypothesis verdict summary ----------
    out.append(section("Hypothesis verdicts"))
    h1 = "ACCEPT" if p < 0.05 and len(groups) > 1 else "REJECT"
    # Use stored values
    anova_p = pd.read_csv(TBL / "04_anova.csv")["p_value"].iloc[0]
    cor = pd.read_csv(TBL / "03_correlations.csv").set_index("variable")
    h1 = "ACCEPT" if anova_p < 0.05 else "REJECT"
    h2 = "ACCEPT" if (cor.loc["altitude_km", "pearson_r"] < 0
                      and cor.loc["altitude_km", "pearson_p"] < 0.05) else "REJECT"
    rain_test = h_df.iloc[0] if not h_df.empty else None
    h3 = "ACCEPT" if (rain_test is not None and rain_test["p_value"] < 0.05) else "REJECT"
    h4 = "ACCEPT" if (cor.loc["elevation_deg", "pearson_r"] > 0
                      and cor.loc["elevation_deg", "pearson_p"] < 0.05) else "REJECT"
    h5 = "ACCEPT" if model.rsquared > 0.5 and model.f_pvalue < 0.05 else "REJECT"
    summary = pd.DataFrame([
        {"hypothesis": "H1: bands differ in SNR (ANOVA)", "verdict": h1,
         "evidence": f"F-test p={anova_p:.3g}"},
        {"hypothesis": "H2: altitude lowers SNR", "verdict": h2,
         "evidence": f"r={cor.loc['altitude_km','pearson_r']:.3f}, "
                     f"p={cor.loc['altitude_km','pearson_p']:.3g}"},
        {"hypothesis": "H3: rain lowers SNR (lat-zone proxy)", "verdict": h3,
         "evidence": (f"t-test p={rain_test['p_value']:.3g}"
                      if rain_test is not None else "n/a")},
        {"hypothesis": "H4: elevation raises SNR", "verdict": h4,
         "evidence": f"r={cor.loc['elevation_deg','pearson_r']:.3f}, "
                     f"p={cor.loc['elevation_deg','pearson_p']:.3g}"},
        {"hypothesis": "H5: altitude+elevation+freq explain SNR",
         "verdict": h5, "evidence": f"R²={model.rsquared:.3f}, "
                                    f"F-p={model.f_pvalue:.3g}"},
    ])
    out.append(summary.to_string(index=False))
    summary.to_csv(TBL / "11_hypothesis_summary.csv", index=False)

    REPORT.write_text("\n".join(out))
    print("\n".join(out))
    print(f"\nReport written to {REPORT}")


if __name__ == "__main__":
    main()
