# Audit of the v0 codebase (`referee/`, `app.py`)

*Phase 0 deliverable. Written 2026-10-19 from findings gathered 2026-10-07 and re-checked today. Every finding gives a
file:line reference or a PDF page, and the appendix has a command that reproduces it.*

## 1. Bottom line

v0 is tidy, heavily commented code with 243 tests, but **its central claims don't hold**, and it can't be trusted for
learning from papers.

The root cause is its purpose. It was built in five days as a competition demo (Polymer Tech Expo,
`replication-referee-plan.md`), designed to issue a *debunking verdict* (REPLICATES / FAILS) rather than to reproduce a
paper's own numbers. Several of its bugs follow directly from that goal:
- the verdict never compares against what the paper reported;
- a golden-test spec compares the wrong strategy and the wrong metric;
- the look-ahead check could never fail on the code it is supposed to police.

**Verdict:** keep the ideas and a handful of components; rewrite the spec, engine, checks and verdict. The rebuild lives
in the new package `replicator/`. v0 stays untouched for reference.

## 2. Inventory (about 9.2k lines, 47 tracked files)

| Module | Lines | Purpose | Tests |
|---|---|---|---|
| `referee/spec.py` | 324 | Strategy Spec v1 (pydantic): `Sourced[T]` with quote and confidence | `test_spec.py` |
| `referee/engine/backtest.py` | 330 | Daily vectorised engine: signal → weights → returns, costs, stats | `test_engine.py` |
| `referee/engine/sandbox.py` | 190 | Subprocess runner for generated code | `test_sandbox.py` |
| `referee/audit/checks.py` | 546 | The six checks | `test_audit.py` |
| `referee/audit/verdict.py` | 328 | Testability gate, verdict, card | `test_audit.py` |
| `referee/data/loaders.py`, `universes.py` | 377 | yfinance cache, coverage accounting, ticker lists | `test_loaders.py` |
| `referee/ai/*` | 576 | `claude -p` client, extraction, code generation, quote verification | `test_client/extract/generate/verify.py` |
| `referee/papers.py` | 400 | Four hand-written reference specs | `test_audit.py` |
| `referee/describe.py`, `feasibility.py` | 560 | English rendering of the spec; limitation grading | `test_describe/feasibility.py` |
| `referee/pipeline.py` | 325 | Five stages, two human gates | `test_pipeline.py` |
| `app.py` | 1,123 | Streamlit UI | `test_app.py` (slow) |

## 3. Test status, and what the tests actually prove

- **Fast suite:** 224 passed (13 s), re-run today.
- **Full suite**, including the 19 slow tests, run in an isolated copy so the real cache is untouched: see §9.
- **What the tests prove is narrower than the README implies:**
  - The look-ahead tests (`tests/test_engine.py:40-62`) prove that `compute_signal` is causal. It is causal by
    construction: a trailing window and a shift. They say nothing about generated code, or about the
    weighting and rebalancing path.
  - The AQR and Ken French reproduction tests assert correlation > 0.6. That measures direction, not magnitude.
  - No test compares any result with a number the paper reported.

## 4. Findings, ranked

### Critical

| # | Finding | Where | How verified |
|---|---|---|---|
| C1 | **The J&T golden spec compares the wrong strategy and the wrong metric.** It backtests 12-month/3-month, but `claimed.annual_return = 9.29%` is the **CAPM alpha (market-model intercept) of the 6-month/6-month strategy, net of 0.5% one-way costs**. The paper's figure for 12/3 is 1.31%/month gross. Quote verification passed it, because the sentence exists | `referee/papers.py:361-372`; J&T PDF p.14 (printed p.77) and p.6 (printed p.69); Table I on PDF p.7 | Text search of the PDF (appendix, command 1) |
| C2 | **The look-ahead check is a tautology.** It blinds only the built-in `compute_signal`, never the weights or rebalance path, and never generated code. The static checker for generated code passed **8 of 9** leaky patterns: `shift(-k)` with a variable, full-sample z-score, `rolling(center=True)`, `pct_change(-1)`, `np.roll`, realignment via `iloc[1:]`, `rank(pct=True)` along the time axis, `read_csv(url)`. It only catches a literal `shift(periods=-1)` | `referee/audit/checks.py:56-121`; `referee/ai/generate.py:43-94` | Command 2 |
| C3 | **Generated code never drives a reported number.** The verdict comes from the hand-written engine. "Cross-engine agreement" compares only the *sign* of the raw signal, which is meaningless for cross-sectional ranks | `checks.py:479-546`; `pipeline.py:282` | Code reading |
| C4 | **The engine can't express what papers specify.** There is no holding period and no J/K overlapping cohorts, and bars are daily only. Weights are held *constant* between rebalances (`ffill` of weights), so drift is never modelled and the implicit daily rebalancing is never charged. Execution happens at the signal bar's close, while the docstring says "trade at Tuesday's open" | `referee/engine/backtest.py:244-257`; `referee/spec.py:210-213` | Code reading |
| C5 | **The verdict doesn't measure replication.** REPLICATES never compares against the paper's numbers, and FAILS mixes up "our data is limited" with "the paper is wrong" | `referee/audit/verdict.py:173-232` | Code reading |
| C6 | **The breadth gate counts panel columns, not names valid on each date.** During J&T's 1965–89 sample the "108-name" universe has only 37 names with data in 1975 and 73 in 1989, i.e. deciles of 4–7 stocks. The gate sees 108 columns and passes | `verdict.py:143-155` | Command 3 |

### High

| # | Finding | Where |
|---|---|---|
| H1 | The out-of-sample split is the publication year, not the paper's sample end. "In-sample" means *our* data's start, labelled as "the period the authors studied" | `checks.py:222-237` |
| H2 | The claim table compares mismatched metrics: arithmetic mean × 252 against whatever the paper reported, here a CAPM alpha | `app.py:282-301`; `backtest.py:318` |
| H3 | **Gaps are filled silently.** `prices.pct_change().fillna(0.0)` plus `ffill` of weights. This breaks the "never fill gaps silently" rule | `backtest.py:249-251` |
| H4 | TSMOM deviates from the paper: 24 instruments vs 58; Sharpe "> 1" is claimed from the *diversified 58-asset* portfolio; vol half-life is 60 days, against the paper's estimator (verify in the MOP PDF); gross-exposure normalisation changes the construction | `papers.py:52-121`; `backtest.py:39-42,163-181` |
| H5 | BLL (technical rules, 1992) is tested on `^DJI` from 1992, which has **zero overlap** with the 1897–1986 sample, and on a price index without dividends | `papers.py:194-260`; cache start date (command 4) |
| H6 | The multiple-testing count is Streamlit session state (robustness sweeps add to it), so the same paper gets different verdicts depending on what you clicked earlier. The t-stat assumes i.i.d. returns (no HAC correction) | `checks.py:418-471`; `app.py:1020` |
| H7 | Quote verification checks that a quote *exists*, not that it *supports the value*, and any run of 6 words counts as a match | `referee/ai/verify.py:57-73` |

### Medium

- The sandbox's `ALLOWED` set is defined but never enforced; the import hook only blocks a blocklist
  (`sandbox.py:54-75`). The README calls it an allowlist.
- Extraction cuts the paper to 60k characters (75% head + keyword paragraphs), which can drop results tables. `page` is
  optional; there are no section or table citations (`extract.py:48-72`).
- The ticker list is *today's* large caps, chosen with 2026 hindsight. That is a selection look-ahead on top of
  survivorship (`universes.py:97-109`).
- The docstring references `check_long_only_sharpe`, which doesn't exist (`backtest.py:289`).
- `describe.py:244-248` says positions are "not continuously re-balanced"; the engine does exactly that implicitly.
- Parameter sensitivity sweeps the lookback only (`checks.py:343-399`); "realistic" costs are hard-coded (`checks.py:129-134`).
- The API client's default model id is stale and it ignores `timeout` (`client.py:125-146`).
- Numbers drift between README, `papers.py` and `feasibility.py`: UMD Sharpe 0.46 vs 0.49; our Sharpe 0.10 / 0.11 / 0.20 / 0.24.
- The price cache has no snapshot or version metadata, so results can't be reproduced after a re-download.

## 5. README claims vs reality

| README claim | Reality |
|---|---|
| "The static check proves the generated code is *safe* and *causal*" | 8 of 9 leak patterns pass (C2) |
| "import allowlist" | A blocklist; the allowlist is never applied |
| "Every non-assumed field claims a verbatim sentence… confirms that sentence actually exists" | True, but existence ≠ support: the J&T 9.29% passed (C1, H7) |
| "Cross-engine agreement… If two independent implementations disagree, one is wrong" | Compares signal signs only; the generated code never produces returns (C3) |
| "Look-ahead bias… delete the future, require the past to be unchanged" | Applied only to the built-in signal function (C2) |
| "No paper currently returns REPLICATES. That is a property of the universe" | Partly. The verdict also never checks the paper's numbers, and the J&T claim is mismatched (C1, C5) |

## 6. Keep / rewrite

**Keep:**

| Item | Why | Fate in v2 |
|---|---|---|
| `Sourced` provenance model with explicit / inferred / assumed grading | Right idea | Extended to `F[T]` with status, citations, approval |
| Quote normalisation (`verify.normalise`) | Handles PDF artefacts | Reimplemented, with exact page-scoped matching |
| Feasibility and limitation surfacing | Honest by design | Becomes the always-on disclosure panel |
| Loader coverage accounting; negative-cache and negative-price fixes | Real lessons | Carried into `replicator/data/prices.py` |
| Balanced long/short legs | Real bug fix | Kept in the J/K engine |
| Drawdown counting initial capital, with known-answer tests | Correct | Kept in `replicator/metrics.py` |
| `FakeLLM` test pattern; versioned prompts; the `claude -p` client; two human gates | Good practice | Kept |

**Rewrite:** the spec schema, the engine, all six checks and the verdict semantics, the code-generation role (generated
code must drive results and trace to the spec), the reference specs, the static checker (replaced by dynamic truncation
and perturbation tests), and `app.py`.

## 7. Requirements gap matrix (your brief vs v0)

| Requirement | v0 |
|---|---|
| 1. Upload a PDF of any strategy type | Partial: PDF yes; the schema covers 4 signal kinds |
| 2. Spec with page/section citations, assumptions approved | Partial: quotes but optional pages; no section or table refs; no reported-results table |
| 3. Readable strategy page | Partial: rendered from spec fields only; no intuition, arguments or limitations |
| 4. Code generated from the approved spec, traceable | Missing in effect: the code is generated but doesn't drive results |
| 5. Strategy + buy-and-hold benchmark; paper vs ours; reasons for gaps | Missing: no benchmark, no like-for-like comparison |
| 6. Six checks with known-answer tests + second-implementation cross-check | Partial: checks exist, but C2, H1 and H6 apply; no cross-library checks |
| 7. Variables tab, baseline kept, alternative universes | Partial: a robustness sweep over lookback only |
| 8. Versioned knowledge base | Missing |
| No look-ahead, with tests | Partial (C2) |
| Survivorship and data limits disclosed on every result | Partial (only below 50% coverage) |
| Costs settable | Partial |
| ML: walk-forward / purged CV, seeds | Missing |
| Never fill gaps silently | Violated (H3) |

## 8. Golden set with v0

| Golden paper | Can v0 do it? |
|---|---|
| J&T (1993) | No: no J/K cohorts; mismatched claim (C1); 4–7 names per decile in-sample (C6) |
| MOP (2012) | No: 24 of 58 instruments; un-roll-adjusted futures from 2000; different construction (H4) |
| Fama-French factor (UMD) | No loader in the product; only a correlation test |
| ML paper (KMZ 2024) | No ML support at all |

## 9. Full-suite run (isolated copy)

**243 passed in 37 s** (2026-10-19, isolated copy in the scratchpad, so the real `data/cache` was untouched). The suite
is green, and that is the point of this audit: every critical finding above exists *alongside* a passing suite,
because the tests check the code against itself rather than against what the papers report.

## Appendix: reproduction commands

1. J&T claim mismatch: `.venv/bin/python -c "from pypdf import PdfReader; r=PdfReader('data/papers/jegadeesh_titman_1993.pdf'); print(r.pages[13].extract_text()[1500:2600]); print(r.pages[5].extract_text()[:2500])"`
2. Static checker probe:
   `.venv/bin/python -c "from referee.ai.generate import check_code; H='import pandas as pd\ndef compute_signal(prices):\n'; [print(n, check_code(H+b)) for n,b in {'var shift':'    k=5\n    return prices.shift(-k)\n','zscore':'    r=prices.pct_change()\n    return (r-r.mean())/r.std()\n','centered':'    return prices.rolling(21,center=True).mean()\n','pct_change(-1)':'    return prices.pct_change(-1)\n'}.items()]"`
   (an empty list means it passed the checker)
3. Breadth by year: count cached `US_LARGE_CAP` tickers whose first price predates each year (`data/cache/prices/*.parquet`).
4. Cache start dates: `^DJI` 1992-01-02; `CL=F` 2000-08-23; `GC=F` 2000-08-30.
