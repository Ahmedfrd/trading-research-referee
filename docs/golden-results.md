# Golden set: our results vs the papers

*Generated 2026-10-19 from `reports/golden/{jt,tsmom,umd,kmz}.json`. Re-run with
`.venv/bin/python -c "from replicator.golden import jt, tsmom, umd, kmz; [m.run() for m in (jt, tsmom, umd, kmz)]"`.*

**Replication levels:**
- **L1:** reproduced from published, CRSP-built third-party data.
- **L2:** our own rebuild on free data, biased in measured ways.
- **L3:** faithful rebuild on the same data the paper used.

**Pass rule** (`checks.check_replication`): all three of
- |ours − paper| ≤ 2 × the combined standard error;
- same sign;
- same significance at 5%.

## Summary

| Paper | Level | Verdict | Headline |
|---|---|---|---|
| **Kelly, Malamud & Zhou (2024)**, ML market timing | **L3** | **Replicates** on Sharpe and information ratios | Nonlinear (P=12,000, T=12): Sharpe **0.467 vs 0.47**, t 4.43 vs 4.5, IR vs market 0.307 vs 0.31. R² differs by 1–2 points |
| **Jegadeesh & Titman (1993)**, Tier 1 | **L1** | **Pass** | Ken French EW momentum D10−D1, 1965–89: **1.33%/mo (t 4.79) vs the paper's 1.49% (t 4.28)**, closest cell (J=12, K=3, Panel B) |
| Jegadeesh & Titman (1993), Tier 2 | L2 | Mostly fails (2 of 16 cells pass) | Our survivor universe is too thin and biased for 1965–89 (median 99 names per formation date). Bias measured below |
| **UMD** (Fama-French library) | L2 | Fails on the mean; **tracks closely** | Correlation **0.89** with Ken French UMD, but mean 0.20% vs 0.51%/mo |
| **Moskowitz, Ooi & Pedersen (2012)** | L2 | Fails on the mean; tracks moderately | Correlation **0.62** with AQR TSMOM^CM; mean 0.40% vs 0.57%/mo; Sharpe 0.28 vs 0.44 |

**Bottom line.**
- The two papers whose claims can be tested on *the right data* pass:
  - KMZ, because its inputs are free;
  - J&T, through Ken French's CRSP-built deciles.
- Every **free-data rebuild of an equity or futures paper falls short in magnitude** while tracking the direction
  (correlations 0.62–0.89). That is the measured cost of survivor-biased, non-roll-adjusted free data, not evidence
  against the papers. The tool reports it as such, not as a verdict on the paper.

## 1. Jegadeesh & Titman (1993): Table I, PDF p.7

**Tier 1 (L1).**
- **The comparison:** Ken French's 10 portfolios formed on prior 2–12 return (equal-weighted, built from CRSP, monthly
  holding), D10 − D1, January 1965 to December 1989.
- **The result:** **1.331%/month, t = 4.79**, against the closest Table I cell (J=12, K=3, 1-week skip): **1.49%, t = 4.28**.
  This is a **pass**.
- **The caveat:** the constructions differ. Ken French uses formation over months 2–12, a 1-month skip and 1-month
  holding; J&T Panel B uses a 12-month formation, 1-week skip and 3-month overlapping holding. Ken French's
  portfolios are re-sorted monthly and can't be turned into J/K cohorts. Tier 1 therefore tests whether **the
  paper's claim reproduces on CRSP-built data**, not our engine.

**Tier 2 (L2): our J/K engine on cached US equities, 16 Panel-A cells.**

| J \ K | 3 | 6 | 9 | 12 |
|---|---|---|---|---|
| 3 | −0.19% vs 0.32% ✗ | −0.06% vs 0.58% ✗ | 0.23% vs 0.61% ✗ | 0.46% vs 0.69% ✓ |
| 6 | −0.17% vs 0.84% ✗ | 0.14% vs 0.95% ✗ | 0.58% vs 1.02% ✗ | 0.48% vs 0.86% ✗ |
| 9 | 0.52% vs 1.09% ✗ | 0.84% vs 1.21% ✓ | 0.75% vs 1.05% ✗ | 0.48% vs 0.82% ✗ |
| 12 | 0.79% vs 1.31% ✗ | 0.67% vs 1.14% ✗ | 0.55% vs 0.93% ✗ | 0.33% vs 0.68% ✗ |

*Ours vs paper, mean buy−sell per month, 1965–89 window. Our data actually starts in 1971 and covers 226 months; median
breadth is 99 names, against all NYSE/AMEX stocks in the paper.*

**Why the gap, measured rather than asserted.** We built the *same* construction as Ken French (prior 2–12, top/bottom
deciles, equal-weighted) on our universe over the same 227 months:

| | Ours | Ken French |
|---|---|---|
| Mean D10 − D1 per month | 1.07% | 1.39% |
| Correlation | 0.69 | |

The free universe captures about three-quarters of the effect. What's missing is survivorship (no delisted firms)
and breadth. The engine's J/K logic is separately proven exact on synthetic data, and against an independent
reference implementation in `tests/rp/test_engine.py`.

## 2. Moskowitz, Ooi & Pedersen (2012)

**Construction:**
- 12-month lookback and 1-month hold;
- each position scaled to a 40% annualised volatility target;
- ex-ante volatility from an EWMA of daily returns with a **centre of mass of 60 days**, annualised by **261**, both
  verified in the PDF on p.10.

The 40% target sits inside an equation the PDF text doesn't expose, so it is marked as *not machine-verifiable*.

**Data:** Yahoo continuous commodity futures from 2000. They are not roll-adjusted, and cover 21 of the paper's 24
commodities and 58 instruments in total.

| vs AQR TSMOM^CM (L1 reference) | AQR | Ours |
|---|---|---|
| Monthly mean | 0.574% (t 2.31) | 0.402% (t 1.45) → **fail** |
| Annualised Sharpe | 0.44 | 0.28 |
| Correlation | | 0.62 |

Monthly returns use month-end prices. Volatility is estimated per contract on its own trading days: the daily panel is on a union calendar, where a contract is NaN on its exchange's holidays. That NaN is not missing data. Overlap with AQR: 331 months (1998-11 to 2026-05).

The paper's text gives no commodity-only Sharpe, so the comparison is against AQR's published series for the same strategy.

## 3. UMD (Ken French momentum factor)

**Construction (L2):** prior 2–12 return, top and bottom 30%, equal-weighted, monthly, on cached US equities.
- There is **no size split and no value weighting**, because free data has no historical shares outstanding before 2009.
- Months with breadth below 100 are excluded: the window is 1980-02 to 2026-08, 559 months, median breadth 429.

| | Ken French UMD | Ours |
|---|---|---|
| Monthly mean | 0.509% (t 2.70) | 0.197% (t 1.03) → **fail** |
| Annualised Sharpe | 0.40 | 0.15 |
| Correlation | | **0.89** |

## 4. Kelly, Malamud & Zhou (2024): Table I, journal p.495 (PDF p.37)

**Data:** the 15 Welch–Goyal predictors, monthly, 1929–2020. Settings:
- random Fourier features (γ = 2);
- ridge regression with z = 10³;
- rolling training window T ∈ {12, 60, 120};
- 20 seeds, against the paper's 1,000.

| T = 12 | Paper | Ours |
|---|---|---|
| Linear: R² | −3.8% | −1.7% |
| Linear: Sharpe (t) | 0.46 (4.4) | 0.459 (4.36) |
| Linear: IR vs market | 0.33 | 0.326 |
| **Nonlinear P=12,000: Sharpe (t)** | **0.47 (4.5)** | **0.467 (4.43)** |
| Nonlinear: IR vs market | 0.31 | 0.307 |
| Nonlinear: IR vs linear | 0.26 | 0.267 |
| Nonlinear: R² | 0.6% | 1.7% |

**How close:**
- Sharpe and information ratios match to about 0.01 at T = 12, 60 and 120 (all rows are in `reports/golden/kmz.json`).
- R² is off by 1–2 points, plausibly due to seed count and data vintage.
- The ridgeless extreme (max loss) does not match.

**Data provenance:** Goyal's updated sheet, taken from a third-party GitHub mirror because his site serves
Google Drive links. Vintage runs to 2025 and is truncated at 2020-12; the sha256 is recorded.

## What would move these numbers

- **Survivorship-free equities.** The WIKI Prices archive to 2018 plus historical S&P membership would shrink the J&T and UMD gaps.
- **Roll-adjusted or synthetic futures.** Building them from FRED rates and index levels would help TSMOM.
- **1,000 seeds for KMZ.** This would test whether the R² gap is noise.
