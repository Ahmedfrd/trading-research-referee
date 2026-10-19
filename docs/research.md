# Research: tools, data, and what free data can't do

*Phase 1 deliverable. Desk research 2026-10-07/08; hands-on items marked **[run]** were exercised in tonight's
build (2026-10-19). Items marked **[desk]** were not installed or run because of the deadline. Treat their
reliability notes as reported, not measured. Full source links are in `docs/plan.md` Appendix C.*

## 1. Paper-to-code and agent systems

| System | What it does | Licence | Reliability notes | Borrow / avoid |
|---|---|---|---|---|
| **Vibe-Trading** (HKUDS) [desk] | Natural language → strategy code; 7 backtest engines; loaders for tushare, yfinance, akshare, ccxt and okx; walk-forward, Monte Carlo and bootstrap validation | MIT | Very active (v0.1.16, 2026-09-29). Issue tracker shows yfinance rate-limit failures. No paper-ingestion or citation feature found | Borrow the validation-suite ideas. Avoid strategy code with no source citations |
| **Microsoft RD-Agent (Q)** [desk] | Hypothesis → task → code (Co-STEER) → backtest loop; `fin_factor_report` extracts factors from reports | MIT | **Linux + Docker only; no macOS.** Built around Qlib and China A-share data | Borrow the loop structure and report-to-factor prompts. Don't adopt |
| **Paper2Code / PaperCoder** [desk] | Plan → analyse → code agents for ML papers | (see repo) | ICLR 2026; evaluated on its own benchmark and PaperBench | Borrow staged planning |
| **DeepCode** (HKUDS) [desk] | Agentic coding, including a paper-to-code workflow | (see repo) | v2 is a general coding agent | Ideas only |
| **PaperCompiler** (arXiv 2609.02272) [desk] | Persistent specifications linking each requirement to code; uncertain details kept explicit | paper | +13.8% fidelity on Paper2CodeBench | **Adopted:** spec fields → code bindings (`replicator/codegen`) |
| **QRAFTI** (arXiv 2604.18500) [desk] | Agentic equity-factor research through tools | paper | Tool-calling beat free code generation | **Adopted:** template families, with the LLM filling parameters |
| **TradingAgents / AI Hedge Fund** [desk] | Trading agents | Apache / MIT | Not paper replication | Out of scope |
| **Claude Code CLI** [run] | `claude -p --output-format json --json-schema` enforces structured output | Anthropic | Works headless on the subscription. Shares the 5-hour and weekly limits. A move to metered billing was announced in May and paused on 2026-06-15; it could return | **Adopted:** extraction + strategy page; cache + usage log |

## 2. Backtest engines

| Engine | Licence | Status | Fit for us |
|---|---|---|---|
| **QuantConnect LEAN** [desk] | Apache-2.0 | Local runs need Docker; the CLI docs say a paid organisation tier; bring-your-own equity data + security master | Too heavy, and not free end to end |
| **vectorbt** [run] | Apache-2.0 + Commons Clause | 1.1.2 installed cleanly (isolated env, Python 3.14) | **Used as the second engine.** On two yardstick strategies, gross returns match ours to about 1e-15; net differences are only cost conventions (fee bar, fee on traded value vs on weight change). See `research/results/cross_engine.md` |
| **backtrader** [desk] | GPL-3.0 | Inactive since 2023-04 | Avoid |
| **zipline-reloaded** [desk] | Apache-2.0 | 3.1.1 (2025-07); Python ≤ 3.13; bundle ingestion | Heavy for monthly academic replications |
| **bt** [desk] | MIT | v1.3.0 | Fine for allocation strategies; not cohort logic |
| **Our engine** [run] | — | `replicator/engine` | **Chosen.** Paper constructions (J/K cohorts, MOP TSMOM) are explicit and tested against a naive independent implementation |

The decision was to write our own engine, because the golden papers need constructions that general engines don't express.
The **second implementations** demanded by requirement 6 are:
- an independent naive implementation inside the tests;
- library cross-checks of every metric (empyrical, statsmodels);
- **vectorbt**, which reproduces our gross returns to machine precision (`research/results/cross_engine.md`).

## 3. ML-quant frameworks

| | Licence | Notes | Decision |
|---|---|---|---|
| **Qlib** [desk] | MIT | pyqlib 0.9.7, cp312 macOS wheels; CN/US Yahoo-derived data whose download status is unclear; US data is survivorship-biased | Borrow the rolling-workflow ideas; don't adopt |
| **FinRL** [desk] | MIT | Reinforcement learning; the literature flags leakage and look-ahead risks | Avoid for replication |
| **skfolio** [desk] | (verify) | Combinatorial purged CV, walk-forward | Use if purged CV is needed beyond the KMZ walk-forward |

## 4. Metrics and statistics

| Library | Notes | Use |
|---|---|---|
| **empyrical-reloaded 0.7.0** [run] | Installs fine with pandas 3 | Cross-check for Sharpe, max drawdown, volatility, CAGR |
| **statsmodels 0.15** [run] | HAC / Newey-West | t-stats with autocorrelation |
| **quantstats** [desk] | Active; a CAGR sign-flip bug was fixed only in Sep 2026 (PR #548) | Not used. A reminder to cross-check, never to trust a single library |
| **alphalens-reloaded** [desk] | Pins pandas < 3 | Not used, because of the pandas conflict |
| **pypbo** [desk] | Deflated Sharpe ratio, probability of backtest overfitting | Our DSR is implemented from the paper's formula and tested |

## 5. Free data, and its biases

| Source | Used tonight | Biases and limits |
|---|---|---|
| **yfinance cache** (Aug–Sep 2026, 561 tickers) [run] | Equities, commodity futures | Survivorship (today's listings); unofficial API with heavy rate limiting in 2026; adjusted history is revised between downloads; delisted firms missing; continuous futures are not roll-adjusted |
| **Ken French Data Library** [run] | FF3, UMD, 10 momentum deciles | Built on CRSP, so it is the best free ground truth. **Revised between vintages**, so we snapshot and hash it |
| **AQR TSMOM factors** [run] | TSMOM reference | Factor returns only (no instruments); terms in a spreadsheet tab |
| **Welch–Goyal predictors** [run] | KMZ golden test | Free and complete for the KMZ design. See `reports/golden/kmz.json` for vintage |
| **Stooq** [desk] | — | **API key required since about Apr 2026**; pandas-datareader dropped its reader |
| **Tiingo free tier** [desk] | — | 500 symbols/month; personal use only |
| **WIKI Prices archive** [desk] | — | About 3,199 US stocks including delisted ones, 1962 to Mar 2018; public domain. A future option to reduce survivorship |
| **FRED / ALFRED** [desk] | — | Free key; point-in-time vintages |
| **SEC EDGAR XBRL** [desk] | — | Point-in-time fundamentals only from about 2009 (large filers) |
| **Chen–Zimmermann, JKP** [desk] | — | Free portfolio returns for 200+ predictors (L1 references) |
| **GKX `datashare`** [desk] | — | Characteristics keyed by CRSP permno; **no returns**, so unusable without CRSP |

## 6. Comparison and recommended architecture

The recommended architecture is the one built tonight:

> PDF → page-anchored text → `claude -p --json-schema` extraction into Spec v2 (citations, assumptions) → code-level
> citation verification → you approve the assumptions → deterministic, traceable code from **template families** →
> our point-in-time engine on snapshot data → strategy + benchmark → paper-vs-ours table + six checks + disclosures →
> SQLite knowledge base.

Why this design:
- Templates make generated code correct by construction.
- The LLM is confined to reading and explaining, which the evidence says it does well, and kept away from computing
  and choosing, which the evidence says it does badly.

## 7. Main risks

1. Free-data bias makes stock-level papers L2 at best.
2. LLM extraction errors, and memorised outcomes leaking in.
3. `claude -p` usage limits, and possible future metered billing.
4. yfinance instability.
5. Template coverage: strategies outside the families are refused, not approximated.

## 8. What *cannot* be faithfully replicated with free data

1. **Stock-level US cross-sectional anomalies before about 1996–2000.** They need CRSP's full history including delisted
   firms and delisting returns.
2. **Accounting-based anomalies before about 2009.** There are no free point-in-time fundamentals.
3. **ML papers on the CRSP/Compustat panel** (e.g. Gu, Kelly & Xiu 2020).
4. **Long-sample futures papers.** There are no free roll-adjusted histories before 2000.
5. **Intraday, order-book, options, analyst, news or proprietary-data papers.**

What *can* be done:
- **L1:** reproduce from published portfolio and factor returns (Ken French, AQR, Chen–Zimmermann, JKP).
- **L2:** independent rebuilds with measured bias.
- **L3:** papers whose inputs are free, e.g. KMZ on Welch–Goyal data.
