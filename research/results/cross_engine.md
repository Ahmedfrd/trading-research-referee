# Cross-engine check: our stack vs vectorbt 1.1.2 (isolated env research/envs/vbt, Python 3.14)
Script: research/experiments/cross_engine.py (modes data|ours|vbt|report). Data: research/results/yardstick_*.parquet.

## Setup
- Y1: 200-day SMA long/flat on ^DJI (level rebuilt as cumprod(1+cached daily return), 1992-01..2026-08, 8,716 days). Signal at close t, held t+1, 5 bps/side.
  Ours = 10-line pandas reference; vbt = from_orders(size=0/1, size_type=targetpercent, fees=5e-4).
- Y2: 12-1 momentum, 30 tickers (us_large_cap_v0[:30], monthly, 679 rows, 5,712 NaN cells = short histories), top/bottom 20%, EW, monthly, 10 bps.
  Ours = cross_sectional_jk(J=11, skip=1, K=1, top_fraction=0.2, cost_bps=10); vbt = from_orders(targetpercent weights, cash_sharing, call_seq=auto, fees=1e-3) on a price index rebuilt from returns. Signal re-derived independently in pandas for vbt.

## Results (per-period returns, overlapping dates)
| Run | n | max abs diff | corr | mean ours / vbt | Sharpe ours / vbt |
|---|---|---|---|---|---|
| Y1 net (5bps) | 8516 | 5.0e-4 | 0.99987 | 0.000195 / 0.000195 | 0.444 / 0.443 |
| Y2 net (10bps) | 666 | 4.1e-3 | 0.99995 | 0.007603 / 0.007582 | 0.348 / 0.347 |
| Y1 gross (fees 0) | 8516 | 2.6e-16 | 1.0 | 0.000213 / 0.000213 | 0.485 / 0.485 |
| Y2 gross (fees 0) | 666 | 9.2e-16 | 1.0 | 0.008759 / 0.008759 | 0.401 / 0.401 |

Gross returns agree to machine precision for both strategies (signal, lag, ranking, leg construction identical).
All net differences come from costs. Re-running with the vbt cost series shifted one bar later: Y1 max diff 3.6e-5, Y2 6.8e-4.

## Convention differences found
1. Cost timing (dominant). vbt debits the fee at the fill bar (close t, hits return of bar t). Ours charges the cost to the first holding period (t+1). A trade's fee therefore lands one bar apart: 5.0e-4 spikes in Y1, up to 4.1e-3 in Y2. Totals agree; per-period alignment does not.
2. Fee base. vbt charges fee x traded value (notional of the order, equity-scaled, compounding). Ours charges bps x sum|w - drifted w_prev| on unit capital (additive, equity-independent). Y1 summed cost 0.1525 ours vs 0.1514 vbt (-0.7%); Y2 0.770 vs 0.784 (vbt +1.8%).
3. Drift/rebalance: both rebalance to target each month from drifted weights (ours via _turnover on drifted weights; vbt targetpercent uses live equity), so turnover matches in principle; residual Y2 cost gap reflects fee-on-value with 200% gross leverage vs on-unit-capital.
4. Cash/leverage: ours treats the long-short as a zero-net return stream (long leg minus short leg, each 1/nl, no collateral, no short financing). vbt holds shorts against a single cash balance (proceeds credited to cash, no borrow cost), so equity base is 1.0 either way; returns match gross, but vbt would diverge if short fees/interest were enabled (neither side does).
5. First period / warm-up: vbt returns include the 200 (Y1) / ~14 (Y2) warm-up bars as zeros that ours omits (only_vbt=200 / 14); the first fill's fee in vbt hits the same bar as the trade. Comparison uses the inner join. Dropping the first overlapping row changes nothing (maxdiff_ex_first identical).
6. Missing data: ours uses nominal weights and renormalises leg returns over valid names; vbt inputs used fillna(0) in the price index (no NaN issue arose in gross agreement, so no observed effect on this sample).

## Verdict
Return mechanics (signals, lags, leg math) are verified against an independent engine to ~1e-15. Net-of-cost series differ only by documented cost conventions (bar of charge, fee-on-value vs fee-on-weight), at most one fee per period and <2% of total cost; Sharpe differs by 0.001. No bug found in our engine. Caveat: Y1 is not exercising cross_sectional_jk (no MA template), so it validates only the yardstick harness, not our library.
