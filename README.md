# CubeSat Communication Link-Budget — Statistical Analysis

Statistical study of how orbital, frequency and environmental factors affect
the SNR and reachable data-rate of CubeSat ground links, using **only public
real-world data** (no Monte-Carlo simulation).

## Data sources (all public, no API key)

| Dataset | URL | What we use |
|---|---|---|
| CelesTrak CubeSat GP/TLE | `https://celestrak.org/NORAD/elements/gp.php?GROUP=cubesat&FORMAT=json` | NORAD ID, mean motion → orbital altitude (Kepler 3) |
| SatNOGS DB transmitters | `https://db.satnogs.org/api/transmitters/` | downlink frequency, mode, baud per CubeSat |
| SatNOGS Network observations | `https://network.satnogs.org/api/observations/` | real ground-station observation records: max elevation, station lat/lng, vetted status (good/bad/failed), observation frequency |

`src/fetch_data.py` downloads everything into `data/raw/`.

## Pipeline

```
fetch_data.py     →  data/raw/*.json   (CelesTrak + SatNOGS)
build_dataset.py  →  data/dataset.csv  (joined + computed link-budget metrics)
analysis.py       →  results/tables/*.csv + results/report.txt  (10 stats methods)
plots.py          →  results/figures/*.png
```

Reproduce:

```
pip install -r requirements.txt
python src/fetch_data.py
python src/build_dataset.py
python src/analysis.py
python src/plots.py
```

## What we compute per observation

For each real SatNOGS observation we derive, from the joined records:

* **Altitude** from CelesTrak mean motion via Kepler's third law:
  `a = (μ / n²)^(1/3)`, altitude = `a − R_⊕`.
* **Frequency band** from `observation_frequency` (VHF / UHF / S / X).
* **Slant range** from spherical geometry given altitude and `max_altitude`
  (the elevation of the pass culmination).
* **Free-space path loss** via the Friis equation
  `FSPL = 20·log₁₀(4π·d/λ)`.
* **Atmospheric gas attenuation** via an ITU-R P.676-style table (oxygen +
  water vapour) scaled by 1/sin(elevation).
* **Rain attenuation** via an ITU-R P.838 specific attenuation `γ = k·R^α`
  with the rain rate selected from the station latitude (tropical / temperate
  / polar climate zones — a published P.837-style proxy).
* **SNR** under typical CubeSat link assumptions (1 W TX, 2 dBi sat antenna,
  band-dependent ground-station gain, 290 K system noise, 9.6 kHz BW). All
  fixed values are listed at the top of `src/build_dataset.py`.

The variation across observations therefore comes entirely from real measured
or published parameters: orbital altitude, transmit frequency, observation
elevation, station latitude.

## Hypotheses tested

| # | Hypothesis | Method |
|---|---|---|
| H1 | Frequency band changes SNR | One-way ANOVA + Kruskal-Wallis + Mann-Whitney post-hoc |
| H2 | Altitude reduces SNR | Pearson/Spearman + simple regression |
| H3 | Rain reduces SNR | t-test (tropical vs polar zone), correlation with `rain_att_db` |
| H4 | Higher elevation raises SNR | Pearson/Spearman + simple regression |
| H5 | Altitude + elevation + frequency jointly explain SNR | Multiple OLS regression (R²) |

## Statistical methods (10 total)

1. Descriptive statistics
2. Shapiro-Wilk normality test
3. Pearson + Spearman correlation
4. One-way ANOVA
5. Kruskal-Wallis non-parametric ANOVA
6. Mann-Whitney U pairwise post-hoc with Bonferroni correction
7. Simple linear regression (per predictor)
8. Multiple linear regression (full model)
9. Two-sample hypothesis tests (rainy vs dry, high vs low elevation,
   successful vs failed observations)
10. 95 % confidence intervals for SNR per band

Numerical results live in `results/tables/` and the formatted summary in
`results/report.txt`. Figures are in `results/figures/`.

## Results on real SatNOGS data (n = 2 648 observations)

Bands present in the joined dataset: **UHF (2 425)**, **VHF (223)**.
The cubesat group on CelesTrak is dominated by amateur UHF/VHF satellites,
so S- and X-band do not appear here; the H1 test therefore compares the two
bands actually present.

| # | Hypothesis | Verdict | Evidence |
|---|---|---|---|
| H1 | Bands differ in SNR | **ACCEPT** | ANOVA F = 233.2, p = 1.6 × 10⁻⁵⁰; UHF mean = 34.6 dB, VHF mean = 38.6 dB |
| H2 | Altitude lowers SNR  | **ACCEPT** | Pearson r = −0.354, p = 3.2 × 10⁻⁷⁹ |
| H3 | Rain (climate-zone proxy) lowers SNR | **ACCEPT** | t-test tropical vs polar p = 6.9 × 10⁻¹², r(rain_att, snr) = −0.565 |
| H4 | Higher elevation raises SNR | **ACCEPT** | r = +0.781, p ≈ 0 |
| H5 | Altitude + elevation + frequency explain SNR | **ACCEPT** | OLS R² = **0.932**, adj-R² = 0.932, F-p ≈ 0 |

Distance (slant range) is the single strongest predictor — Spearman ρ = −0.86 —
and elevation explains 61 % of the SNR variance on its own. The full multiple
regression reaches R² = 0.93, confirming that link-budget physics dominates the
observed signal-quality variation in the SatNOGS data.

A real outcome label is also available: SatNOGS' `vetted_status`. The
two-sample test on this label (`successful` vs `failed` observations,
n = 1 948 vs 700) gives t = 9.83, p ≈ 9 × 10⁻²², so observations that
volunteer ground stations actually decoded successfully also have a higher
computed SNR — an external sanity check that the link-budget calculation is
tracking real radio behaviour, not just an artefact of the formula.

Generated artefacts:
- `data/dataset.csv` — observation-level dataset with link-budget columns
- `results/tables/01_descriptive.csv` … `11_hypothesis_summary.csv`
- `results/report.txt` — formatted summary
- `results/figures/01_snr_by_band.png` … `09_success_vs_snr.png`

## Notes / limitations

* SatNOGS `vetted_status` reflects volunteer ground-station decoding success;
  it is **a real outcome label** but is also influenced by station quality,
  not just the link budget.
* The atmospheric/rain models are simplified ITU-R-style approximations; the
  full P.676 / P.838 line-by-line implementation is out of scope.
* We freeze TX power and antenna gains as per-band constants because SatNOGS
  does not expose station-by-station antenna calibration data. The README
  discloses every fixed value so the analysis is fully reproducible.
