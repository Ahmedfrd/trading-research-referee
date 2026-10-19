# Referee rebuild — master plan, all phases

*Written 2026-10-07; agent-hierarchy section (§11) added 2026-10-08. Status: **awaiting your approval**. Nothing
has been built yet. The only actions taken so far are read-only (reading code, running the fast tests, web research).*

---

## 0. How to read this

- **§1–3** are the decisions and rules. **§4** is the plan, phase by phase. **§5–10** are the
  designs and lists the phases refer to. **§11** is the multi-agent hierarchy: the research, how workable it is,
  the design, and what to build. The appendices hold the evidence.
- **What has been researched:**
  - Every module of the existing code was read. The fast tests were run (224 passed), and the code was probed
    (see Appendix A).
  - Desk research covered every tool, data source and paper in your brief, plus related work it turned up
    (Appendix C).
  - J&T's Table I was transcribed from your PDF (Appendix B).
- **What has *not* been done yet:**
  - Hands-on installs and test runs of each tool. That is Phase 1, and it can't happen inside planning.
  - Some facts come from search-engine summaries rather than primary pages, because the page-reading
    agents hit a usage limit. Those are marked **(verify P1)**, and Phase 1 confirms or corrects every one.

---

## 1. Goal, constraints, decisions

**Goal.** A tool you trust enough to learn from trading research papers. Accuracy, and honesty
about limitations, come before features.

**Constraints.** Free data and free tools, run locally on your MacBook, Python + Streamlit, and Claude through your
existing subscription (`claude -p`).

| Decision | Choice | Made |
|---|---|---|
| LLM backend | Claude Code CLI on your subscription | 2026-10-07 |
| UI | Python + Streamlit | 2026-10-07 |
| Six checks | Revised set proposed in §6, for approval at the Phase 2 gate | 2026-10-07 |
| ML golden paper | Kelly, Malamud & Zhou (2024), *The Virtue of Complexity in Return Prediction* | 2026-10-07 |
| Fama-French golden factor | UMD (momentum) | 2026-10-07 |
| J&T acceptance | Two tiers (see §7; **Tier 1 wording corrected, re-confirm at P2**) | 2026-10-07 |
| Existing code | Tag it as `v0-expo`, build a fresh package in this repo, port only the audited "keep" pieces | 2026-10-07 |
| Agent design | Verified pipeline (code orchestrator, narrow LLM roles, code checks first, blind reviewers) **plus an experimental LLM supervisor**, kept only if fault-injection shows it adds value (§11) | 2026-10-08 |
| Disagreement handling | The reviewer settles **clear-cut** disagreements under a strict, code-checked rule (§11.6); everything else, and all assumptions, come to you; every auto-resolution is logged and can be undone | 2026-10-08 |
| Model diversity | Claude only, no local models. Diversity comes from different prompts, reading orders and model tiers | 2026-10-08 |
| Agent run mode | **Thorough by default** (all roles on every new paper); economy mode is opt-in | 2026-10-08 |

**Working rules (from your brief):**
- Each phase ends with **STOP**: I show the output and wait for your approval.
- No product code in Phases 0–2.
- I ask instead of assuming.
- No commits unless you ask. I suggest one branch per phase.

---

## 2. Design rules (what the audit and the research taught us)

1. **Every result is labelled with its replication level:**
   - **L1, reproduced from published data.** The authors' or a third party's portfolio returns
     (Ken French, AQR, Chen–Zimmermann, JKP).
   - **L2, independent rebuild on free raw data.** Biased in known, measured ways.
   - **L3, faithful rebuild on the same data the paper used.** Rarely possible for free. KMZ is the one golden case where it is.
2. **The paper's own numbers are the yardstick.** Comparisons must be like for like: same metric, period, strategy
   variant, gross or net, raw or risk-adjusted. There is no verdict that ignores what the paper reported.
   (The old tool compared J&T's 6/6 CAPM alpha against a 12/3 raw return; see Appendix A, C1.)
3. **Look-ahead is prevented by structure, not by spotting it.** Strategy code only ever receives a
   point-in-time view of data. Truncation and perturbation tests then run on the *whole* pipeline, including generated code.
4. **Nothing happens silently.** Every fill, dropped row, approximation and assumption is recorded and
   shown on screen next to the result it affects.
5. **The LLM reads and explains; it never chooses.** Every statement it makes carries a verified citation:
   page, exact quote, and the value actually present in that quote or table cell. It never picks parameters
   by performance and is never asked for a number that isn't in the PDF. Recent research shows LLMs leak
   memorised outcomes into finance work (Appendix C, LLM look-ahead).
6. **Two independent implementations for every number that matters.** Our engine is checked against a second
   engine. Our metrics are checked against empyrical, quantstats and statsmodels.
7. **Everything is reproducible.** Each run stores a manifest: PDF hash, spec version, code hash, data-snapshot
   hashes, library versions and random seeds. Re-opening a run reproduces identical numbers.
8. **Agents check each other only through artifacts and real checks, and you are the final supervisor.** Code runs the
   workflow, LLM roles are narrow and blind to each other's reasoning, and a role stays only if fault-injection shows it
   catches errors the code checks miss (§11).

---

## 3. Phases at a glance

| # | Phase | Main deliverable | Product code? |
|---|---|---|---|
| 0 | Audit | `docs/audit.md` | No |
| 1 | Hands-on research | `docs/research.md`, plus throwaway experiments in `research/` | No |
| 2 | Design | `docs/design/*.md`: architecture, spec schema v2, engine conventions, six checks, golden protocol, UI flows | No |
| 3 | Foundation | New package skeleton, data layer with snapshots and provenance, reference datasets, metrics with cross-checks | Yes |
| 4 | Engine + engine-level golden tests | Point-in-time engine, J/K cohorts, costs, benchmark, cross-engine tests; J&T, TSMOM and UMD built from hand-verified specs | Yes |
| 5 | Agent runtime, paper ingestion and extraction | Orchestrator + review queue; PDF → cited spec v2 via two blind analysts and a reviewer; citation verification; assumption approval; readable strategy page | Yes |
| 6 | Code generation | Spec → traceable code inside the point-in-time harness, dynamic look-ahead tests, human code approval | Yes |
| 7 | Results and the six checks | Paper vs ours with gap attribution, benchmark, six checks, a disclosure panel on every result | Yes |
| 8 | ML strategies | Walk-forward and purged/embargoed CV, fixed seeds, leakage tests; KMZ golden test | Yes |
| 9 | Variables tab and knowledge base | Editable parameters with the paper's baseline locked; versioned store of papers, specs, code and runs | Yes |
| 10 | End-to-end acceptance | `docs/golden-results.md`: all four golden papers run from PDF; hardening; an honest README | Yes |

**Why this order.** The data and engine are proven against known answers in Phases 3–4, using
hand-verified specs, *before* the LLM enters the loop in Phase 5. Once extraction is added, any
mismatch can then be traced to extraction rather than to the engine. The Streamlit UI grows page by page
from Phase 5 on, so you can use each part as it lands.

---

## 4. The phases in detail

### Phase 0 — Audit → `docs/audit.md`

Most of the investigation is already done (summary in Appendix A).

1. **Isolated verification run.** Copy the repo, minus `.venv`, into a scratch folder and run it there. This keeps
   your `data/cache/` untouched, because the slow tests would delete expired cache markers and could download
   from Yahoo.
   - Run the full test suite, including the 19 slow tests.
   - Re-measure the README's headline numbers: J&T verdict and Sharpe, TSMOM vs AQR correlation, momentum vs UMD correlation.
2. **Write `docs/audit.md`** with these sections:
   - bottom line
   - inventory
   - test status, and what the tests actually prove
   - ranked findings, each with `file:line` and how it was verified
   - README claims vs reality
   - keep / rewrite tables
   - requirements gap matrix
   - assessment of the existing six checks
   - feasibility of each golden test with the current code
   - an appendix of every reproduction command

**Acceptance.** Every finding is reproducible from the appendix. `git status` shows only the new doc.
**STOP.**

### Phase 1 — Hands-on research → `docs/research.md`

**Setup.**
- One throwaway virtualenv per tool, made with `uv` under `research/envs/` (gitignored).
- Experiment scripts live in `research/experiments/`. They are research, not product, and are committed only if you ask.
- A shared, frozen price snapshot is used by every engine test, so results are comparable.

**Common yardsticks**, run in every engine with the conventions spelled out:
- **Y1:** a 200-day moving-average long/flat rule on SPY. Daily, 2005–2024, 5 bps one-way cost.
  Signal at close *t*, trade at close *t+1*.
- **Y2:** 12-1 month cross-sectional momentum. Top minus bottom quintile, equal weight, a fixed 30-stock panel, 10 bps.
- **Y3:** J/K overlapping-cohort momentum (J=12, K=3) on the same panel. Tests whether an engine can express
  J&T's design at all.
- **The reference** is a hand calculation in plain pandas, a research script and not product code.
  An engine passes when its daily returns match the reference to ≤1e-6 once conventions are aligned.
  Every convention difference gets written down.

**1A — Paper-to-code and agent systems**

| System | What we know | Hands-on test | Expectation |
|---|---|---|---|
| Vibe-Trading (HKUDS) | MIT; v0.1.16 on 2026-09-29; ~34.7k stars. Turns natural language into strategy code, with 7 backtest engines, data loaders (tushare, yfinance, akshare, ccxt, okx), and walk-forward / Monte Carlo / bootstrap validation | Install; run one strategy; read the generated code for look-ahead; check whether it can use Claude without a paid API key | Borrow its validation-suite ideas and research memory. Avoid natural-language-to-code with no citations |
| Microsoft RD-Agent (Q) | MIT; NeurIPS 2025. **Linux + Docker only, no macOS.** Has a `fin_factor_report` scenario that extracts factors from reports. LLMs via LiteLLM | One-hour time-boxed try in Docker Desktop; otherwise read the code for the report-to-factor flow | Borrow the hypothesis → task → code → evaluate loop and its extraction prompts. Don't adopt (platform, and Qlib China data) |
| Paper2Code / PaperCoder | ICLR 2026. Plan → analyse → code stages | Check for a free LLM path; if none, desk review only | Borrow staged planning |
| DeepCode (HKUDS) | Agentic coding; Paper2Code workflow (licence: verify P1) | Desk review | Ideas only |
| PaperCompiler (arXiv 2609.02272) | Persistent specs that link each requirement to code, keeping uncertain details explicit | Read | **Closest to our design.** Borrow requirement-to-code traceability |
| "What Papers Don't Tell You" (2603.01801) | Recovering tacit knowledge in paper reproduction | Read | Feeds how we handle assumptions |
| QRAFTI (2604.18500) | Tool-calling beats dynamic code generation for empirical finance research | Read | Supports the template + tool approach in Phase 6 |
| Agentic Empirical Asset Pricing (2609.00731) | Evaluation standards for agent-discovered factors | Read | Informs the checks |
| TradingAgents, AI Hedge Fund | Trading agents, not paper replication | Desk note only | Out of scope |
| Claude CLI itself | `--json-schema` enforces structured output. Headless PDF reading has a known poppler issue (#29886) | Extract J&T with `--json-schema`; try PDF reading in headless mode; measure time and tokens; observe the subscription's rate limits | Decides the extraction design |

**1B — Backtest engines.** Run Y1–Y3 in each.

| Engine | Known facts | Things to settle hands-on |
|---|---|---|
| QuantConnect LEAN | Engine is open source. Local runs need Docker, and the docs say the CLI needs a paid organisation tier (verify P1). Equity data is bring-your-own and needs a security master | Can it be built from source with .NET for free? Time-boxed. Delisting handling |
| vectorbt | 1.1.1 (2026-09-26); Apache 2.0 + Commons Clause (free to use, can't be sold); Python 3.11–3.14; pandas 3 OK | Its conventions; whether it can express J/K cohorts |
| backtrader | 1.9.78.123 (2023-04-19); GPL-3.0; inactive | Python 3.12+ compatibility |
| zipline-reloaded | 3.1.1 (2025-07-19); Python 3.10–3.13; csvdir bundles | Custom bundle; trading calendars |
| bt | MIT; v1.3.0 (date: verify P1) | Rebalancing and commission model |

**1C — ML-quant frameworks.**
- **Qlib:** pyqlib 0.9.7 (2025-08-15); MIT; cp312 macOS wheels. Check its data-download status and US-data survivorship (verify P1).
- **FinRL:** MIT; reinforcement-learning focus.
- For both: install, run the tutorial, and audit for leakage and point-in-time correctness.
- Expectation: borrow ideas (Qlib's expression engine and rolling workflow), not adopt either as the core.

**1D — Metrics and statistics libraries.**
- **Libraries:**
  - **quantstats:** active; a CAGR sign-flip bug was fixed in Sep 2026 (PR #548).
  - **empyrical-reloaded:** 0.5.11.
  - **alphalens-reloaded:** **pins pandas < 3**, which clashes with this repo's pandas 3.0.5.
  - **pyfolio-reloaded:** 0.9.9.
  - **statsmodels:** for Newey-West standard errors.
  - **skfolio:** combinatorial purged CV and walk-forward (licence: verify P1).
  - **pypbo:** Deflated Sharpe and probability of backtest overfitting.
  - **purged-cross-validation:** MIT.
- **The test.** Three synthetic return series with closed-form answers, plus one real series. Compute Sharpe,
  Sortino, CAGR, volatility, max drawdown, alpha/beta and t-stats in each library, and record every disagreement
  and its cause (annualisation, risk-free rate, ddof, compounding).
- **Outcome.** The pandas-version decision.

**1E — Free data.** Fetch from each source, inspect it, and *measure* its biases.

| Source | Known facts | What to measure |
|---|---|---|
| yfinance | Unofficial scraper of Yahoo's web endpoints; heavy rate limiting in 2026; adjusted closes are back-adjusted and change over time; delisted tickers missing | Adjusted vs raw + dividends; drift between snapshots; what share of 2000's S&P 500 is still retrievable |
| Stooq | **Needs an API key since about Apr 2026**; pandas-datareader 0.11 removed its reader | Get a key; check coverage, including delisted names |
| Tiingo free tier | 500 unique symbols/month, 50 requests/hour, 1,000/day; personal use only | Whether delisted names are covered (verify P1) |
| Quandl/Nasdaq WIKI Prices archive | About 3,199 US stocks including delisted ones, 1962 to Mar 2018; public domain; mirrored on Kaggle | Coverage by year against CRSP-like counts; adjustment quality |
| fja05680/sp500 | Historical S&P 500 membership since 1996 | Usable as a point-in-time universe |
| FRED / ALFRED | Free key, 120 calls/min; vintages give point-in-time macro data | Risk-free rate; inputs for synthetic futures |
| Ken French Data Library | Factors and portfolios (10 momentum deciles, equal- and value-weighted; 6 size × momentum). pandas-datareader's FamaFrench reader is still maintained. **History is revised between vintages, especially HML** | Snapshot it and record the vintage |
| SEC EDGAR XBRL | companyfacts/frames with filing dates (point-in-time); large filers from mid-2009; 10 requests/s; User-Agent required | Point-in-time book equity and shares outstanding for 50 firms |
| AQR data library | TSMOM *original paper data*: 1985–2009, 58 instruments, by asset class; terms in a tab of the spreadsheet | Reference series for MOP |
| Open Source Asset Pricing (Chen–Zimmermann) | 200+ predictor portfolio returns (Oct 2025 release, to Dec 2024); firm-level signals come without returns | Whether J&T momentum portfolios are included (verify P1) |
| JKP Global Factor Data | 153 factors, 93 countries, through Dec 2025; CC BY-NC 4.0 | Second reference for UMD-like factors |
| Welch–Goyal predictors (Amit Goyal's site) | Monthly data through 2025 | **KMZ golden input** |
| GKX `datashare.zip` | 94 characteristics keyed by permno, **no returns** (those need CRSP) | Documented as unusable without CRSP |
| Futures | Yahoo continuous contracts (2000+, not roll-adjusted); TurtleTrader free daily data (1970s+, verify P1); Nasdaq CHRIS deprecated; synthetic futures built from FRED (FX + rate differentials; bond yields → duration approximation) and index levels + T-bills | TSMOM correlation against AQR, by asset class |

**1F — PDF ingestion bake-off.**
- **Inputs:** the 6 PDFs in `data/papers`, plus MOP and KMZ.
- **Tools:** pypdf, PyMuPDF, docling, marker, MinerU (if it installs on a Mac), and Claude reading the PDF via the CLI.
- **Ground truth:** J&T Table I (Appendix B).
- **Metrics:** table-cell accuracy, correct page attribution, time per paper.

**1G — Bias-quantification experiments**, which feed the disclosure panel:
- our survivor-universe momentum deciles vs Ken French's deciles over the same period
- WIKI vs yfinance where they overlap
- adjusted-price drift between two snapshots.

**1H — Agent-hierarchy experiment (§11).**
- Read the key work: MAST, LLM-Modulo, AgentCoder, N-version coding agents, the correlated-errors paper, Anthropic's
  and Cognition's write-ups.
- **Experiment on the J&T PDF.** Compare a single extraction with two blind extractions plus a spec reviewer.
  - Plant 10 known errors. Five are in specs (including CAPM alpha used as a raw return); five are in code
    (including `shift(-1)` and an off-by-one J/K cohort).
  - For each setup, measure catch rate, false alarms, tokens, time, and how close it runs to the 5-hour limit.
- **Also measure** how often the clear-cut rule settles items wrongly, and what the experimental supervisor pass catches
  that the other roles don't.
- **Test the CLI features** `claude -p --json-schema` and `--agents`.
- Local models are out of scope (your choice, 2026-10-08).

**Deliverable: `docs/research.md`.**
- One section per tool covering what it does, licence, measured reliability, and what to borrow or avoid.
- A comparison table.
- The recommended architecture (§9, confirmed or revised).
- Main risks (§10).
- The honest statement of what can't be replicated (§8).

**STOP.**

### Phase 2 — Design → `docs/design/`

No product code. Documents for you to approve:

- **`architecture.md`:**
  - modules, data flow and interfaces
  - dependency pins
  - Python and pandas version decision
  - the second engine chosen from Phase 1
  - the PDF parser chosen from Phase 1
- **`spec-schema-v2.md` + JSON Schema:** see §5.
- **`engine-conventions.md`:**
  - decision time; execution price (close *t*, open *t+1* or close *t+1*)
  - drift between rebalances; overlapping cohorts
  - cost model (one-way bps on traded notional, plus optional spread and borrow cost)
  - risk-free rate and cash handling
  - delisting-return policy; missing-data policy (never filled silently)
- **`checks.md`:** the final six checks, with formulas, thresholds, synthetic known-answer cases and the cross-check source for each (§6).
- **`golden-protocol.md`:** for each golden paper, the exact variant, period, data, metric, tolerance rule and pass definition (§7).
  The proposed default tolerance:
  - **Against a paper's estimate:** a pass needs all three of:
    - the difference is within 2 × the combined standard error (the paper's SE comes from its own t-stat);
    - the sign is the same;
    - the result is significant, or not, at 5% in both.
  - **Against a reference series (AQR, Ken French):** correlation and mean difference must clear thresholds that are set from Phase 1 measurements.
- **`codegen.md`:**
  - templates first, with the LLM filling in only parameters and non-template signal functions (§9);
  - the traceability scheme.
- **`ui-flows.md`:** the page list and wireframes, including the Review queue and Agent trace pages.
- **`agents.md`:**
  - role cards (job, allowed inputs, output schema, forbidden actions, checklist)
  - the workflow state machine for each stage
  - budgets per paper and per role, revision caps, escalation rules
  - economy mode
  - the fault-injection error catalogue (§11)
- **`migration.md`:**
  - the package name (proposal: keep `referee`, move the old code to `legacy/` after tagging `v0-expo`, delete `legacy/` once porting is done and you approve)
  - the port list from the audit.

**STOP.**

### Phase 3 — Foundation (product code starts)

- **Project setup:**
  - tag `v0-expo`
  - a `uv` project with pinned dependencies
  - ruff for linting
  - pytest markers: `network`, `slow`, `golden`, `llm`
  - CI-style local script: `make check` runs lint + offline tests
- **Data layer:**
  - one provider interface, with providers for yfinance, Tiingo, the WIKI archive, Stooq (optional), FRED/ALFRED, Ken French, AQR, EDGAR, Goyal, Chen–Zimmermann and JKP
  - **immutable snapshots:** parquet + sha256 + a metadata JSON recording source, URL, retrieval time, vintage, adjustments and licence
  - a `DataProvenance` object on every dataset
  - a `GapReport`: missing data is reported, never filled silently
  - coverage and bias reports
  - a point-in-time universe (S&P 500 membership)
- **Metrics module:**
  - returns; arithmetic vs geometric annualisation; volatility
  - Sharpe on *excess* returns, using the FRED risk-free rate; Sortino
  - max drawdown; turnover
  - alpha/beta by OLS with Newey-West errors; t-stats
- **Tests:**
  - closed-form synthetic cases
  - cross-checks against empyrical-reloaded, quantstats and statsmodels, to 1e-10 or with the convention difference documented
  - offline fixtures for every provider.
- **Acceptance:** all offline tests pass; snapshot hashes reproduce; metrics cross-checks pass. **STOP.**

### Phase 4 — Engine and engine-level golden tests

- **Point-in-time accessor.** Strategy code sees `view(t)`, which contains only data stamped at or before decision time.
  Property-based tests (hypothesis) cover truncation (deleting the future changes nothing before it) and
  perturbation (changing the future changes nothing before it).
- **Engine primitives:**
  - time-series signals
  - cross-sectional sorts, with quantile breakpoints optionally taken from a sub-universe (NYSE-style)
  - **J/K overlapping cohorts**
  - equal and value weights; volatility targeting
  - explicit execution conventions
  - holdings drift between rebalances, with its turnover charged
  - costs
  - daily and monthly frequency
- **Benchmark.** Buy-and-hold over the same period, data and costs. For long/short strategies, also the market and risk-free returns.
- **Cross-engine.** Y1–Y3 and every golden construction are re-run in the second engine chosen in Phase 1, and tests assert agreement.
- **Golden tests with hand-written, citation-verified specs (no LLM yet):**
  - **J&T:** the J/K engine is checked exactly on synthetic data. Tier 1 and Tier 2 reports are produced (§7).
  - **MOP TSMOM:** an L2 rebuild by asset class, compared to AQR's original paper data.
  - **UMD:** an L2 rebuild compared to Ken French's UMD.
- **Acceptance:** engine and cross-engine tests pass; golden reports exist with pass/fail against the tolerance you approved, and every failure is explained, never hidden. **STOP.**

### Phase 5 — Paper ingestion, extraction, strategy page

- **Agent runtime (§11.7)**, built first in this phase:
  - `agents/runner.py` (cached `claude -p` calls with token and time accounting);
  - `agents/orchestrator.py` (state machine that resumes after a usage-limit pause);
  - the artifact board and the audit trail;
  - the Review queue and Agent trace pages.

  All of it is tested with `FakeLLM`.
- **Ingest.** The Phase 1 winning parser produces a `PaperDocument`: pages, sections, paragraph ids, and tables as cell
  grids with page and table ids, plus the PDF's hash.
- **Extraction roles (§11.6):**
  - Paper analysts A and B extract independently;
  - a field-level diff separates agreement from disagreement;
  - the spec reviewer adjudicates disagreements;
  - the reviser gets at most 2 rounds;
  - anything unresolved goes to the Review queue.
- **Extract** with `claude -p --output-format json --json-schema <spec v2>`, in passes:
  1. inventory the strategy variants and the results tables;
  2. fill the spec fields for the variant(s) you choose;
  3. extract reported results (table, row, column, value, units, gross/net, period, metric, raw vs risk-adjusted);
  4. a self-critique pass that lists unspecified items as ASSUMPTION candidates.
- **Verify every citation:**
  - the exact quote is on the cited page (normalised exact match, not the old 6-word fragment match);
  - each number appears in the cited text or table cell;
  - units are consistent;
  - **the variant matches:** a result's variant id equals the spec's variant id. This rule would have caught the J&T 9.29% bug.
- **Assumption approval.** Each assumption shows its default, rationale and alternatives. You approve or edit it,
  and approvals are stored with a timestamp. Code generation is blocked until every assumption is approved.
- **Strategy page (requirement 3).** Core idea, intuition, mechanics, the authors' arguments, results and limitations.
  Every factual sentence cites a page. Our own commentary is visually separate, as "Referee notes".
  A writer drafts it; a fact-checker then verifies it: a code quote check, plus an LLM judging "does this quote
  support this sentence?".
- **LLM controls:**
  - numbers come only from the PDF
  - a caveat about memorised knowledge
  - caching keyed by PDF hash, prompt version and model
  - graceful handling of subscription rate limits.
- **Extraction accuracy.** Hand-made gold specs for J&T, MOP, KMZ and the 4 arXiv papers. Field-level precision and recall
  are reported. Proposed thresholds, to approve at Phase 2:
  - ≥95% on fields the paper states explicitly;
  - 100% valid citations;
  - zero unflagged assumptions.
- **UI:** Library/Upload, Strategy page, Spec review & assumption approval. **STOP.**

### Phase 6 — Code generation and traceability

- **Templates first.** The spec maps to a template family: time-series signal, cross-sectional J/K sort,
  2×3 factor sort, or ML pipeline. Templates are hand-written and heavily tested. The LLM fills in only declared
  parameters, and writes free-form signal functions only for signals outside the templates, always inside the point-in-time harness.
- **Traceability:**
  - generated code carries a `SPEC_BINDINGS` table linking each constant and function to a spec field path;
  - an AST test asserts that every spec field is used and that no literal is unbound;
  - the UI shows code and spec side by side.
- **Look-ahead on generated code.** Dynamic truncation and perturbation tests on synthetic and real data are the main guard.
  The static scan is kept as a lint only; the old one missed 8 of 9 leak patterns.
- **Sandbox.** A subprocess with a real, enforced import allowlist (the old `ALLOWED` set was never applied), no
  network modules, and CPU and time limits. The threat model is code that is wrong, not code that is hostile.
- **Code roles (§11.6):**
  - The Coder and a **blind Test designer** work from the approved spec. The Test designer writes known-answer
    tests without seeing the code, the AgentCoder pattern.
  - The runner executes the tests, the look-ahead harness and traceability.
  - A code reviewer checks the code against the spec with a checklist.
  - The reviser gets at most 2 rounds.
  - A failing test is never auto-deleted; it goes to the Review queue.
- **Human code-approval gate**, kept from v0.
- **Acceptance:** the golden papers, generated from *extracted* specs, reproduce the Phase 4 hand-built results to
  numerical tolerance. **STOP.**

### Phase 7 — Results, comparison, six checks, disclosures

- Run the strategy and the buy-and-hold benchmark over the same period, data and costs. Costs are settable by you.
- **Paper vs ours table.** One row per reported result (table cell): our matched number, the difference, and the tolerance verdict.
- **Gap-attribution checklist.** Each likely reason is quantified where possible (for example, by re-running on the paper's period only):
  - universe coverage %
  - survivorship
  - period mismatch
  - data vendor and adjustments
  - cost model
  - rebalancing approximation
  - metric definition
  - assumptions in force.
- **Results analyst (§11.6).** Drafts the gap explanation from the computed table only. A **number-consistency check**
  (code) confirms every number in the text matches a computed value, and a reviewer checks the reasoning.
  No LLM ever computes a number.
- **The six checks (§6).** Each has synthetic known-answer unit tests and a cross-check implementation.
- **Disclosure panel on every result:**
  - replication level
  - data sources and snapshots
  - survivorship status
  - coverage and gaps
  - assumptions
  - costs.
- **UI:** Results page. **STOP.**

### Phase 8 — ML strategies and the KMZ golden test

- **Harness:**
  - walk-forward with expanding or rolling windows
  - purged/embargoed K-fold and combinatorial purged CV, from skfolio or our own implementation cross-checked against it
  - the paper's own split whenever it gives one
  - fixed seeds and deterministic flags
- **Leakage tests:**
  - every feature timestamp is ≤ decision time
  - target alignment
  - scalers and other preprocessing are fitted on training data only.
- **Leakage reviewer (§11).** An LLM reviewer with a leakage checklist reads ML code against the spec, in addition to the
  leakage tests, never instead of them.
- **KMZ replication:**
  - data: the 15 Welch–Goyal predictors, monthly
  - model: random Fourier features up to ~12k, ridge regression over a shrinkage grid
  - training: rolling windows of 12 months, plus the paper's other window lengths
  - strategy: market timing
  - comparison: the paper's out-of-sample R², Sharpe and alpha, with exact numbers extracted from the paper in P1/P5
  - cross-check: a second ridge-on-random-features implementation (closed-form numpy vs scikit-learn).
- **Acceptance:** KMZ within tolerance; leakage tests pass. **STOP.**

### Phase 9 — Variables tab and knowledge base

- **Variables tab (requirement 7):**
  - every spec parameter is editable, and the paper's original values stay locked as a visible baseline;
  - alternative universes show whether they're feasible (data, breadth, period);
  - every re-run is a new version, with a diff against the baseline;
  - a multiple-testing counter per paper (variants the paper itself tested plus variants you ran) feeds the significance check.
- **Knowledge base (requirement 8):**
  - SQLite holds papers, versioned specs, assumption approvals, code versions, runs, results and notes;
  - a content-addressed artifact store holds PDFs, data snapshots, code and result files;
  - each run has a manifest; any run can be exported as a folder;
  - PDFs stay local and gitignored, as in v0, because of copyright.
- **Acceptance:** re-opening a saved run reproduces identical numbers from the stored snapshots. **STOP.**

### Phase 10 — End-to-end acceptance and hardening

- Run all four golden papers end to end: PDF upload → spec → approvals → code → results. Compare against the
  Phase 4 and Phase 8 results. Write `docs/golden-results.md`: results vs paper, replication level, pass/fail,
  and explanations.
- **Generality check.** Run the 4 arXiv PDFs plus 2 new papers of different types (e.g. value, carry). The tool should either
  replicate them or refuse with a specific reason.
- **Agent fault-injection evaluation (§11.7).** Run the full planted-error catalogue across all stages.
  - For each role, report catch rate, false alarms, tokens and time in `docs/agent-evaluation.md`.
  - You decide which roles stay. A role stays only if it catches errors the code checks miss, at a cost you accept.
- **Hardening:**
  - error handling and rate limits
  - an offline mode that runs from snapshots
  - performance
  - a README rewrite where every claim links to a test or a reproducible command.
- **STOP.** You decide whether the tool now counts as "working".

---

## 5. Strategy Spec v2 — draft fields (finalised in Phase 2)

Every field is an object with these parts:
- `value`
- `status`: `stated | derived | assumed | unknown`
- `citations[]`: page, section, table, exact quote
- `derivation_note`
- `assumption`: default, rationale, alternatives, `approved_by`, `approved_at`

| Section | Fields |
|---|---|
| paper | title, authors, year, venue, `pdf_sha256`, sample period(s), the data sources the authors used |
| variants | every strategy variant the paper tests (e.g. J&T's 32 J/K/skip combinations), with ids; which ones we replicate |
| universe | asset class, exchanges, inclusion filters (price, size), breakpoint basis (e.g. NYSE), stated asset count, whether point-in-time membership is needed |
| data | frequency, price field (total return?), sample start/end, risk-free rate |
| signal | formula (structured + text), formation window *in the paper's own units*, skip, normalisation |
| portfolio | family (time-series / cross-sectional / factor sort / ML), ranking and quantiles, **holding period K, overlapping cohorts**, weighting, volatility target or leverage, legs, rebalance schedule and timing |
| execution | decision time, execution price and lag, cost model and bps, borrow cost, delisting treatment |
| benchmark | one or more |
| ml | features, target, model and hyperparameters, train/validation/test dates or window, CV scheme, seeds |
| reported_results | metric, value, units, period, **variant_id**, gross/net, **raw / CAPM-alpha / FF-alpha**, table/figure, row, column, page, quote |
| meta | `schema_fit`, extraction notes, prompt version, model |

---

## 6. The six checks — proposed (approve at the Phase 2 gate)

| # | Check | Question it answers | Known-answer synthetic test | Second implementation |
|---|---|---|---|---|
| 1 | Look-ahead (causality) | Does any part of the pipeline, including generated code, use the future? | An injected leak must be detected; a clean strategy must pass | Independent recompute on truncated data |
| 2 | Replication fidelity | Do we match the paper's reported numbers, like for like, within tolerance? | A synthetic series with known mean and SE | statsmodels t-test |
| 3 | Transaction costs | Net results across a cost grid; break-even bps; turnover | Constant-turnover synthetic series with an exact cost drag | vectorbt or bt fee model |
| 4 | Significance and multiple testing | Newey-West t-stat; Bonferroni/Holm and the Harvey-Liu-Zhu t>3 bar; Deflated Sharpe, counting the paper's variants plus yours | i.i.d. normal and AR(1) synthetic series with known distributions | statsmodels HAC, pypbo, scipy |
| 5 | Out-of-sample decay | Paper's sample vs post-sample vs post-publication, with minimum windows and confidence intervals | A synthetic regime break at a known date | empyrical recompute |
| 6 | Parameter sensitivity | Across *all* numeric parameters: is the result a plateau or a spike? | Synthetic plateau and spike surfaces | Independent loop vs vectorbt parameter grid |

**Moved out of the checks:**
- **Cross-engine agreement** becomes a mandatory test-suite invariant (Phases 4 and 6).
- **Data and survivorship disclosure** becomes the always-on disclosure panel (Phase 7).

---

## 7. Golden-set protocol (targets; tolerances approved at Phase 2)

| Paper | What we compare | Ground truth | Level | Pass means |
|---|---|---|---|---|
| **Jegadeesh & Titman (1993)** | Table I: J,K ∈ {3,6,9,12}; Panel A no skip, Panel B 1-week skip; equal-weight deciles; NYSE+AMEX, 1965–1989 | Appendix B (transcribed from your PDF, p.7 = printed p.70) | Tier 1 = L1, Tier 2 = L2 | See the tiers below |
| **Moskowitz, Ooi & Pedersen (2012)** | TSMOM 12-month lookback / 1-month hold, by asset class and diversified, 1985–2009 | AQR original paper data (58 instruments) | L2 | Correlation and Sharpe within tolerance by asset class; coverage reported (instruments obtained vs 58) |
| **UMD (Fama-French library)** | Our 6 size × prior 2–12 portfolios → UMD, on a point-in-time S&P 500 universe (1996+). Value-weighted with EDGAR shares from 2009; equal-weighted before that | Ken French UMD, snapshot of a recorded vintage | L2 | Correlation and mean difference within tolerance; attenuation measured and disclosed |
| **Kelly, Malamud & Zhou (2024)** | Market-timing out-of-sample R², Sharpe and alpha against model complexity | The paper's tables (extracted in P1/P5) | **L3** (same free data) | Within the SE-based tolerance |

**J&T tiers, with the corrected wording.**
- **Tier 1:**
  - J&T's Table I is compared with the *closest constructions* that third parties have built on CRSP and publish free:
    - Ken French's 10 momentum deciles, equal-weighted, 2–12 month, monthly holding;
    - Chen–Zimmermann's J&T momentum portfolios (availability: verify P1).
  - This tests whether **the paper's claim reproduces on the paper's kind of data**.
  - It is *not* an exact J/K rebuild. Ken French's portfolios are re-sorted monthly and can't be turned into J/K cohorts.
- **Tier 2:**
  - Our stock-level J/K engine runs on the best free universe: the WIKI archive to 2018 plus survivors, with coverage measured.
  - The engine itself is proven exact on synthetic data.
  - The gap to Table I is attributed using measured data bias: our 2–12 deciles vs Ken French's 2–12 deciles over the same years.
- **Pass:**
  - Tier 1 is within tolerance of the corresponding Table I cell;
  - the engine is exact on the synthetic tests;
  - Tier 2 is reported with its quantified bias attribution.

---

## 8. Draft: what *cannot* be faithfully replicated with free data

Finalised in `docs/research.md`. Current honest draft:

1. **Stock-level US cross-sectional anomalies before about 1996–2000.** These need CRSP's complete history,
   including delisted firms and their delisting returns. The free archives (WIKI) are partial and skewed
   toward firms that survived into the 2000s.
2. **Anything built on accounting data before about 2009** (value, profitability, investment, accruals, quality).
   There are no free point-in-time fundamentals. EDGAR XBRL only starts for large filers in mid-2009.
3. **ML papers on the CRSP/Compustat panel** (e.g. Gu, Kelly & Xiu 2020). The free characteristics need CRSP returns.
4. **Futures papers with long samples.** Roll-adjusted contract histories before 2000 aren't free, so we can only build
   approximations (synthetic futures, unadjusted continuous contracts).
5. **Papers needing data with no free source:**
   - intraday data, TAQ, order books
   - options (OptionMetrics)
   - analyst forecasts (I/B/E/S)
   - news and text feeds
   - proprietary or vendor indices
   - most international equity panels
6. **What *can* be done:**
   - **L1 reproductions** from published portfolio and factor returns (Ken French, AQR, Chen–Zimmermann, JKP);
   - **L2 rebuilds** with measured bias on recent US data;
   - **L3 replications** of papers whose inputs are themselves free (e.g. Welch–Goyal-based predictability and ML-timing papers such as KMZ).

---

## 9. Recommended architecture (preliminary; confirmed in Phase 1 and fixed in Phase 2)

```
referee/                 (new package; old code moved to legacy/ after tagging v0-expo)
  ingest/      PDF → PaperDocument (page-anchored text and tables)
  spec/        Spec v2 models + JSON Schema, citations, assumptions
  extract/     claude -p --json-schema passes, citation verification
  explain/     readable strategy page with cited claims
  data/        providers, immutable snapshots, provenance, point-in-time universes, gap reports
  engine/      point-in-time accessor, portfolio primitives, execution conventions, costs, benchmark
  strategies/  template families (time-series, cross-sectional J/K, factor sort, ML pipeline)
  codegen/     spec → bound code, traceability, sandbox, dynamic look-ahead tests
  checks/      the six checks (pure functions) + known-answer tests
  ml/          walk-forward / purged CV / CPCV, seeds, leakage audits
  kb/          SQLite + artifact store, run manifests
  agents/      role cards, runner (claude -p), orchestrator (state machine), disagreement diff, audit trail
  verify/      registry of code checks that return structured findings for agents and the UI
  ui/          Streamlit multipage app (incl. Review queue, Agent trace)
```

**Tentative choices:**
- `uv` for environments.
- Python 3.12, chosen for the widest wheel support, unless Phase 1 shows 3.13 works throughout.
- pandas version: decided in Phase 1.
- Our own engine, cross-checked against vectorbt or bt.
- PDF parser: docling or marker, decided by the bake-off.
- statsmodels, empyrical, quantstats, pypbo and skfolio for the cross-checks.
- SQLite + parquet for storage.

---

## 10. Main risks and mitigations

| Risk | Mitigation |
|---|---|
| Free-data bias makes most stock-level papers non-replicable, and the tool could still imply confidence | Replication-level labels, the always-on disclosure panel, measured bias attribution, honest refusals |
| LLM extraction errors, or memorised knowledge leaking in | Verified citations with value-in-quote and variant matching; human approval of assumptions; the LLM never asked for numbers or parameter choices |
| Subscription limits or outages for `claude -p` (planning already hit a session limit) | Cache keyed by PDF hash and prompt version; resumable passes; extraction is the only stage that needs the LLM |
| yfinance blocking, Stooq's new key requirement, Tiingo quotas | Multiple providers behind one interface; immutable local snapshots; offline mode |
| Library conflicts (alphalens vs pandas 3) | Version decision in Phase 1; a separate cross-check environment if needed |
| "Any strategy type" is unbounded | Template families plus explicit `schema_fit` refusals; the generality check in Phase 10 measures coverage honestly |
| Scope and effort (11 phases) | A gate after every phase; each phase stands on its own and is useful by itself |
| Agents agree with each other on the same wrong answer (correlated errors), creating false confidence | Code checks come first; blind roles; disagreement treated as the signal; agreement alone is never treated as proof; you at the gates |
| Anthropic resumes moving `claude -p` to metered credits, multiplying the cost of every agent | Per-role on/off switches and economy mode; budgets; caching; the runner can switch to an API-key backend if you ever choose one |
| Auto-settled disagreements are wrong | Strict code-checked clear-cut rule; always-escalate list; every auto-settlement visible and reversible; measured error rate with automatic revert to manual |
| Agent workflow complexity grows faster than its value | A fixed state machine, not free chat; fault-injection decides which roles stay; roles added one phase at a time |

---

## 11. Agent hierarchy — research, verdict, design

*Added 2026-10-08 at your request.*

### 11.1 What you proposed

Multiple agents (manager, supervisor, analyst, coder, reviser, checker, reviewer) so that AI answers, calculations and
code are checked, rechecked and supervised by other agents.

### 11.2 What the evidence says

| Finding | Source | What it means for us |
|---|---|---|
| Multi-agent systems mostly fail from bad specification (41.8% of failures) and agents misaligning (36.9%), then weak verification (21.3%). The same model working alone sometimes does better | MAST: 150 annotated traces, 14 failure modes | Roles need typed contracts, a fixed workflow and stop rules, not open conversation |
| Multi-agent setups use about 15× the tokens. They win on breadth-first research that splits into independent threads, and do less well on tightly coupled work like coding | Anthropic, *How we built our multi-agent research system* | Add agents only where the work is truly independent, e.g. two blind readings of one paper |
| Reliable setups keep one main loop that holds state and makes every change; extra agents are stateless and narrow, contributing "intelligence rather than actions" | Cognition, *Don't Build Multi-Agents* and its 2026 update | One writer per artifact; reviewers are read-only |
| Without external feedback, models can't reliably fix their own reasoning, and sometimes make it worse (GPT-4: 95.5% → 91.5% after self-review) | Huang et al., ICLR 2024 | A "reviser" only helps when it's fed concrete findings from a real check |
| Put the LLM inside a generate → test loop with sound external verifiers | LLM-Modulo (Kambhampati et al., ICML 2024) | The "checker" should be code wherever possible |
| LLM errors are correlated: on one benchmark, models agree 60% of the time when both are wrong, and judges favour their own model family | *Correlated Errors in LLMs* (ICML 2025); family-preference studies | A Claude reviewer of Claude's work is a weak check on its own |
| Debate between copies of one model rarely beats simpler methods (no method above a 20% win rate vs chain-of-thought across 36 setups); mixing different models helps | *Stop Overvaluing Multi-Agent Debate* (2025) | No debate rounds. Diversity matters more than headcount |
| A test-writer that never sees the code raised pass rates *and* used fewer tokens than heavier multi-agent frameworks | AgentCoder | Worth copying: a blind test designer |
| AI coding agents often fail on the same tricky specs, yet majority voting across three versions cut failures by about 66% | *N-Version Programming with Coding Agents* (2026), redoing Knight & Leveson (1986) | Independent versions help but aren't truly independent. *Disagreement* is the useful signal |
| Role-play "software companies" (ChatDev, MetaGPT) improved executability, at much higher time and token cost | ChatDev / MetaGPT evaluations | Don't copy the company metaphor |
| Research-replication agents are still weak: best PaperBench score about 21–26%, near 0% on actually matching results. AI-scientist systems fabricate results, and claims are harder to verify than code is to run | PaperBench; AI Scientist evaluation; *Verification Gap* survey (2026) | Agents can't be the source of truth. Computed numbers and verified citations are |

### 11.3 Practical constraints on your setup

- **Usage limits.** `claude -p` draws from the same 5-hour and weekly limits as your normal Claude use. During this
  planning, three agents running in parallel hit the session limit. A hierarchy multiplies the number of calls.
- **Billing-policy risk.** In May 2026 Anthropic announced moving `claude -p` and Agent SDK usage onto a separate
  metered credit ($20–200/month, billed at API rates). It was **paused on 2026-06-15**, and Anthropic says it will give
  notice before anything changes. If it returns, every extra agent costs real money.
- **No Agent SDK.** It can't use your subscription login (API key only since Feb 2026). We would drive `claude -p`
  ourselves, as the current code already does.
- **No framework.** LangGraph, CrewAI, PydanticAI and Microsoft Agent Framework are MIT or Apache licensed, but they are
  built around API keys. A small orchestrator of our own around `claude -p` is simpler, and matches the "start simple"
  advice in Anthropic's *Building effective agents*.
- **One model family.** Your subscription offers Opus, Sonnet and Haiku only, and **you chose to stay Claude-only**
  (no local models).
  - Diversity therefore comes from different prompts, different reading orders (text-first vs tables-first) and different model tiers.
  - The research says that is weaker diversity than mixing model families. So the code checks and you remain the genuinely
    independent checks, and agreement between agents is never treated as proof.

### 11.4 Verdict

**Workable and worth building, in a specific form.**

- **Build:** a *verified pipeline with specialist agents*.
  - Code, not an LLM, runs a fixed workflow.
  - Each LLM role does one narrow job and produces a typed artifact.
  - Every artifact goes through **code checks first**. Where judgement is needed, it then goes to an **independent
    reviewer that never sees how the artifact was produced**.
  - Revisions are capped at 2 rounds. Disagreements come to **you**.
- **Don't build:**
  - an LLM manager delegating to an LLM supervisor that oversees other LLMs in open conversation;
  - LLMs checking calculations;
  - debate rounds.

  The evidence above says this would produce confident agreement rather than verification: correlated errors,
  about 15× the cost under your usage limits, and lost context between agents.
- **Your choice (2026-10-08):** the verified pipeline **plus an experimental LLM supervisor**.
  - The supervisor reads the whole run (spec, code, results, check findings and review log) before it reaches you, and
    adds findings to the Review queue.
  - It is read-only, runs one pass, and can't change anything.
  - It stays only if fault-injection shows it catches errors that nothing else catches.
- **The core idea.** "Checked and rechecked" comes from **different kinds of checks**, not from more agents. There are four
  kinds, and each catches errors the others miss:
  1. **Code checks:** citations, schema, tests, the look-ahead harness.
  2. **An independent second implementation:** engine vs engine, our metrics vs libraries.
  3. **A blind second LLM reading:** two independent extractions; a test designer who never sees the code.
  4. **You.**

### 11.5 Your roles, mapped

| Your role | What it becomes | LLM or code | Phase |
|---|---|---|---|
| Manager | **Orchestrator.** A state machine that runs stages in order, enforces budgets and stop rules, retries, resumes after a usage-limit pause, and logs everything | Code | 5 |
| Supervisor | **You**, at the gates, working from one **Review queue**. Plus an **experimental LLM supervisor**: one read-only pass over the whole run before it reaches you, which adds findings to the queue and summarises what needs your attention. Kept only if fault-injection shows unique catches | You + LLM (experimental) | 5, evaluated in 10 |
| Analyst | **Paper analyst A** (extraction) and **Paper analyst B** (independent, blind extraction). **Results analyst** (explains gaps using only the computed tables) | LLM | 5, 7 |
| Coder | **Coder.** Fills template parameters, or writes non-template signals, from the approved spec only | LLM | 6 |
| Reviser | Not a separate persona. The agent that produced the work is re-run with the specific findings. At most 2 rounds, then it escalates to you | LLM | 5–8 |
| Checker | **Code verifiers:** schema; citation, quote, value and variant checks; test runner; look-ahead harness; traceability; cross-engine and metric cross-checks; a number-consistency check on any text. Plus one LLM: a **Test designer** that writes known-answer tests from the spec without seeing the code | Code (+ one LLM) | 5–8 |
| Reviewer | **Independent reviewers** with checklists. They see only the artifact and its sources, never the producer's reasoning: spec reviewer, code reviewer, explanation fact-checker, ML leakage reviewer. The spec reviewer **settles clear-cut disagreements itself** (rule in §11.6) and escalates the rest | LLM | 5–8 |
| (Calculations) | **Never done by an LLM.** Numbers are computed in code, cross-checked by a second implementation and covered by known-answer tests. Text may only quote computed numbers, and a checker enforces that | Code | 3–8 |

### 11.6 How it runs, stage by stage

**Extraction:**

```
              PDF (page-anchored text and tables)
                 │
        ┌────────┴─────────┐
   Analyst A           Analyst B          blind to each other; different reading order
        │                  │
   [code checks]      [code checks]       schema · quote on cited page · value in quote · variant match
        └────────┬─────────┘
              [diff]                      fields that agree → accepted; fields that disagree → adjudication
                 │
          Spec reviewer (LLM)             sees page excerpts only; picks A / B / neither / ambiguous; must cite
                 │
        [clear-cut rule, in code]         passes → auto-settled and logged   fails → escalated
                 │
          Reviser (≤ 2 rounds)            fixes failed checks only
                 │
     LLM supervisor (experimental)        one read-only pass over the whole run; adds findings
                 │
        REVIEW QUEUE → YOU                escalations, all assumptions, supervisor findings, auto-settled items (undoable)
```

**What counts as "clear-cut".** The reviewer may settle a disagreement only when **all** of these hold, and code checks
each one rather than the reviewer:
1. The chosen value is exactly one of A's or B's values; the reviewer can't invent a third.
2. The reviewer cites a quote that the code check finds verbatim on the cited page, and the chosen value appears in that
   quote or table cell.
3. The quote does not also contain the rejected value, or a competing value of the same kind.
4. The field is not in an **always-escalate** class:
   - assumptions (requirement 2 says you approve these);
   - which strategy variant to replicate;
   - reported-result metric type (raw vs risk-adjusted, gross vs net);
   - universe and sample period.

Anything else is escalated. Auto-settled items appear in the Review queue as "auto-settled" with their evidence, and
one click reverses them. Fault-injection measures how often auto-settling is wrong. If it is wrong more often than a
threshold you set at Phase 2, it reverts to manual.

**The other stages:**
- **Strategy page:**
  1. A writer drafts it.
  2. A fact-checker reviews it: the quote check runs in code, plus an LLM judging "does this quote support this sentence?".
  3. Up to 2 revisions, then it comes to you.
- **Code:**
  1. The Coder and the Test designer work in parallel from the spec, blind to each other.
  2. The runner executes the tests, the look-ahead harness, traceability and a synthetic cross-engine check.
  3. The code reviewer checks the code against the spec with a checklist.
  4. Up to 2 revisions, then you approve.

  A failing test is never deleted automatically. Either the code or the test is wrong, and that goes to the queue.
- **Results:**
  1. The engine computes everything; a second implementation must agree.
  2. The Results analyst drafts the gap explanation from the computed table.
  3. The number-consistency check and a reviewer go over it, then it comes to you.
- **ML:** the same as Code, plus the leakage reviewer and the leakage tests.

### 11.7 What we need to build

| Component | Purpose |
|---|---|
| `agents/roles/`: versioned role cards | One per role: its job, the inputs it may see (each agent's context is kept separate), its output JSON schema, forbidden actions, and a checklist |
| `agents/runner.py` | Wraps `claude -p --output-format json --json-schema … --model … --system-prompt …`. Tools are off by default. Results are cached, keyed by role, prompt version, input hash and model. Retries with backoff on rate limits; token and time accounting. Backends: the Claude CLI and `FakeLLM` for tests. The interface leaves room for an API key later, if you ever choose one |
| `agents/orchestrator.py` | An explicit state machine per stage. State is saved in SQLite, so a run resumes after hitting a usage limit. Budgets per paper and per role, capped revision rounds, escalation rules |
| Artifact board (in the knowledge base) | Agents communicate only through typed artifacts (drafts, findings, diffs, verdicts), never free chat. Each artifact records who made it and from which inputs |
| `verify/` registry | The code checks from Phases 3–7, returning structured findings the reviser can act on |
| `agents/disagreement.py` | Field-level diff of independent outputs, adjudication records, the **clear-cut rule** (code), the always-escalate list, and one-click reversal of auto-settled items |
| Supervisor role card (experimental) | Read-only, one pass over the whole run's artifacts and findings. It outputs findings only, never edits. Switched on by default while it is being evaluated |
| Audit trail + "Agent trace" page | For every call: prompt, response, model, tokens, time and hashes, viewable per paper |
| "Review queue" page | Everything waiting on you in one list: disagreements, assumptions, failed checks, code approval |
| Settings | Turn roles on or off, choose a model per role, set budgets. **Default: thorough** (all roles, including the experimental supervisor). Economy mode (one extraction plus code checks) is opt-in |
| **Fault-injection evaluation** | **The deciding piece.** We plant known errors and measure what each role catches. In specs: wrong lookback, wrong variant, flipped sign, CAPM alpha used as a return (the real J&T bug). In code: `shift(-1)`, an off-by-one J/K cohort, costs in % instead of bps. In text: a wrong number. For each role we measure catch rate, false alarms and cost. **A role stays only if it catches errors the code checks miss, at a cost you accept** |
| Tests | Orchestration tested with `FakeLLM` (deterministic), plus resume, budget and schema-contract tests |

### 11.8 Cost and time (rough; measured in Phase 1)

- The old tool took about 3 minutes per extraction on Opus (README: 183 s).
- The thorough default needs roughly **11–17 model calls per new paper**:
  - two extractions, one adjudication, and up to two revisions;
  - a writer and a fact-checker;
  - a coder, a test designer and a code reviewer, plus revisions;
  - a results analyst and a reviewer;
  - one supervisor pass.
- My rough estimate is **30–60+ minutes** per new paper, using a noticeable share of a 5-hour window. Re-runs hit the cache and cost nothing.
- **How thorough-by-default stays inside your limits:**
  - agents run one after another, never in parallel;
  - the orchestrator saves state after every call, so hitting a limit pauses the run instead of failing it, and it resumes in the next window;
  - caching;
  - Sonnet or Haiku for reviewers wherever fault-injection shows they're good enough.

  Economy mode remains available.

### 11.9 Where it lands in the phases

- **Phase 1 (new item 1H):**
  - Read the key work above.
  - A mini-experiment on J&T: one extraction vs two blind extractions plus a reviewer, with planted errors. Measure catch rate,
    tokens, time and how the usage limits behave.
  - Measure how often the clear-cut rule settles items wrongly, and what the supervisor pass adds.
  - Test `claude -p --json-schema` and `--agents`.
- **Phase 2:** `docs/design/agents.md` covering roles, contracts, workflow, budgets, the clear-cut rule, the always-escalate
  list and the error threshold for reverting auto-settling.
- **Phase 5:** the runtime (runner, orchestrator, audit trail, review queue), the extraction roles and the fact-checker.
- **Phase 6:** the Coder, the blind test designer and the code reviewer.
- **Phase 7:** the Results analyst and the number-consistency check.
- **Phase 8:** the leakage reviewer.
- **Phase 10:** the full fault-injection evaluation. Each role, including the experimental supervisor and the
  auto-settling rule, is kept or dropped on its measured value.

---

## 12. Open decisions and when they're made

| Decision | Made at |
|---|---|
| Second engine; PDF parser; pandas and Python versions; whether LEAN is usable | End of Phase 1 |
| Model tier per role | End of Phase 1 (from 1H measurements) |
| Final six checks; spec v2; tolerance numbers; codegen approach; package and legacy handling; J&T Tier 1 wording | Phase 2 gate |
| Agent roles, budgets, the clear-cut rule, the always-escalate list, and the error threshold for reverting auto-settling (`agents.md`) | Phase 2 gate |
| Extraction accuracy thresholds | Phase 2 gate, measured in Phase 5 |
| Which 2 extra papers go into the Phase 10 generality check | Phase 9 gate |
| Which agent roles stay, including the experimental supervisor and auto-settling, from the fault-injection results | Phase 10 gate |

---

## Appendix A — Audit findings so far (full detail in `docs/audit.md`, Phase 0)

The existing code was built in 5 days as a competition demo (Polymer Tech Expo). It was designed to produce a
*debunking verdict*, not a faithful replication. Fast tests: **224 passed, 19 slow not yet run.**

**Critical**
- **C1.** The J&T golden spec backtests 12-month/3-month, but its `claimed.annual_return = 9.29%` is the **CAPM alpha of the
  6-month/6-month strategy, net of 0.5% costs** (PDF p.14 and p.6). The UI compares it with our raw annual return.
  Quote verification passed it because the sentence exists. (`referee/papers.py:361-372`)
- **C2.** The look-ahead check only blinds the built-in `compute_signal`. The static checker passed **8 of 9** leaky patterns
  (variable negative shift, full-sample z-score, centred rolling window, `pct_change(-1)`, `np.roll`, realignment via `iloc[1:]`,
  rank along the time axis, `read_csv(url)`). (`referee/audit/checks.py:56-121`, `referee/ai/generate.py:43-94`)
- **C3.** Generated code never drives a reported number. "Cross-engine" compares only the *sign* of the raw signal.
  (`checks.py:479-546`, `pipeline.py:282`)
- **C4.** The engine has no holding period and no J/K cohorts, and is daily only. Weights are held constant between
  rebalances, so drift and the hidden daily rebalancing are never charged. Execution is at the signal bar's close,
  while the docs say "next open". (`referee/engine/backtest.py:244-257`, `referee/spec.py:210-213`)
- **C5.** REPLICATES never compares against the paper's numbers, and FAILS mixes up data limits with the paper being wrong.
  (`referee/audit/verdict.py:173-232`)
- **C6.** The breadth gate counts panel columns. During J&T's sample the universe has only 37–73 names with data,
  which makes deciles of 4–7 stocks, yet the gate sees 108. (`verdict.py:143-155`)

**High**
- **H1.** The out-of-sample split uses the publication year, not the paper's sample end. (`checks.py:222-237`)
- **H2.** The claim table compares mismatched metrics. (`app.py:282-301`)
- **H3.** Gaps are filled silently. (`backtest.py:249-251`)
- **H4.** TSMOM deviates from the paper: 24 instruments vs 58; the claim is taken from the diversified portfolio; the volatility estimator
  differs (verify P1); and normalising gross exposure changes the construction.
- **H5.** BLL (the technical-rules paper) is tested on data with no overlap with its sample, using a price index without dividends.
- **H6.** The multiple-testing count is session state, so verdicts can't be reproduced; the t-stat assumes i.i.d. returns.
- **H7.** Quote verification checks that a quote exists, not that it supports the value, and any 6-word run counts as a match.

**Medium**
- The sandbox allowlist is never enforced.
- Extraction truncates papers at 60k characters, which can drop results tables.
- The ticker list was chosen with 2026 hindsight.
- The code references `check_long_only_sharpe`, which doesn't exist.
- `describe.py` prose contradicts the engine.
- Parameter sensitivity sweeps the lookback only.
- The "realistic" costs are hard-coded.
- The API client's model id is stale.
- Numbers drift between README, `papers.py` and `feasibility.py`.
- The price cache has no snapshot metadata.

**Worth keeping:**
- the `Sourced` provenance model and the explicit/inferred/assumed grading
- the idea behind quote normalisation
- the feasibility and limitations panel
- the loader's coverage accounting and its negative-cache and negative-price fixes
- balanced long/short legs
- the drawdown fix and its tests
- the subprocess harness
- the `FakeLLM` test pattern
- versioned prompts
- the CLI client
- the two human gates.

---

## Appendix B — J&T (1993) Table I ground truth (buy − sell, average monthly return, t-stat)

Source: Jegadeesh & Titman (1993), Table I, printed p.70, PDF page 7. Equal-weighted deciles, January 1965 to December 1989.

**Panel A — formed immediately after the J-month formation window**

| J \ K | 3 | 6 | 9 | 12 |
|---|---|---|---|---|
| 3 | 0.0032 (1.10) | 0.0058 (2.29) | 0.0061 (2.69) | 0.0069 (3.53) |
| 6 | 0.0084 (2.44) | 0.0095 (3.07) | 0.0102 (3.76) | 0.0086 (3.36) |
| 9 | 0.0109 (3.03) | 0.0121 (3.78) | 0.0105 (3.47) | 0.0082 (2.89) |
| 12 | 0.0131 (3.74) | 0.0114 (3.40) | 0.0093 (2.95) | 0.0068 (2.25) |

**Panel B — formed 1 week after the formation window**

| J \ K | 3 | 6 | 9 | 12 |
|---|---|---|---|---|
| 3 | 0.0073 (2.61) | 0.0078 (3.16) | 0.0074 (3.36) | 0.0077 (4.00) |
| 6 | 0.0114 (3.37) | 0.0110 (3.61) | 0.0108 (4.01) | 0.0090 (3.54) |
| 9 | 0.0135 (3.85) | 0.0130 (4.09) | 0.0109 (3.67) | 0.0085 (3.04) |
| 12 | 0.0149 (4.28) | 0.0121 (3.65) | 0.0096 (3.09) | 0.0069 (2.31) |

**Not a Table I number:** the 9.29%/year on p.77 is the 6/6 strategy's *risk-adjusted* return (market-model intercept),
after a 0.5% one-way cost.

---

## Appendix C — Sources used in planning

**Agents and paper-to-code**
- [HKUDS/Vibe-Trading](https://github.com/HKUDS/Vibe-Trading) · [README](https://github.com/HKUDS/Vibe-Trading/blob/main/README.md)
- [microsoft/RD-Agent](https://github.com/microsoft/rd-agent) · [R&D-Agent-Quant, arXiv 2505.15155](https://arxiv.org/abs/2505.15155)
- [Paper2Code](https://github.com/going-doer/Paper2Code) · [arXiv 2504.17192](https://arxiv.org/pdf/2504.17192)
- [HKUDS/DeepCode](https://github.com/HKUDS/DeepCode)
- [PaperCompiler, arXiv 2609.02272](https://arxiv.org/abs/2609.02272)
- [What Papers Don't Tell You, arXiv 2603.01801](https://arxiv.org/pdf/2603.01801)
- [QRAFTI, arXiv 2604.18500](https://arxiv.org/abs/2604.18500)
- [Agentic Empirical Asset Pricing, arXiv 2609.00731](https://arxiv.org/abs/2609.00731)
- [TradingAgents](https://github.com/TauricResearch/TradingAgents)

**LLM look-ahead**
- [Look-Ahead-Bench, arXiv 2601.13770](https://arxiv.org/abs/2601.13770)
- [HindsightBench, arXiv 2607.18867](https://arxiv.org/html/2607.18867v1)
- [Temporal Leakage in LLM Backtesting, arXiv 2608.02985](https://arxiv.org/pdf/2608.02985)

**Claude CLI**
- [Run Claude Code programmatically](https://code.claude.com/docs/en/headless)
- [Read tool / poppler in headless mode, issue #29886](https://github.com/anthropics/claude-code/issues/29886)

**Engines**
- [LEAN CLI deployment](https://www.quantconnect.com/docs/v2/lean-cli/backtesting/deployment) · [LEAN CLI US equities data](https://www.quantconnect.com/docs/v2/lean-cli/datasets/quantconnect/download-in-bulk/us-equities)
- [vectorbt on PyPI](https://pypi.org/project/vectorbt/) · [vectorbt licence](https://vectorbt.dev/terms/license/)
- [backtrader on Snyk](https://snyk.io/advisor/python/backtrader)
- [zipline-reloaded on PyPI](https://pypi.org/project/zipline-reloaded/)
- [bt releases](https://github.com/pmorissette/bt/releases)

**ML-quant and metrics**
- [pyqlib on PyPI](https://pypi.org/project/pyqlib/)
- [quantstats PR #548](https://github.com/ranaroussi/quantstats/pull/548)
- [empyrical-reloaded releases](https://github.com/stefan-jansen/empyrical-reloaded/releases) · [alphalens-reloaded pyproject](https://github.com/stefan-jansen/alphalens-reloaded/blob/main/pyproject.toml)
- [skfolio CombinatorialPurgedCV](https://skfolio.org/generated/skfolio.model_selection.CombinatorialPurgedCV.html)
- [pypbo](https://github.com/esvhd/pypbo) · [Deflated Sharpe ratio](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf)

**Data**
- [yfinance rate limits, issue #2422](https://github.com/ranaroussi/yfinance/issues/2422)
- [Stooq API key, pandas-datareader issue #1012](https://github.com/pydata/pandas-datareader/issues/1012) · [pandas-datareader Fama-French reader](https://pydata.github.io/pandas-datareader/readers/famafrench.html)
- [Tiingo end-of-day data](https://www.tiingo.com/products/end-of-day-stock-price-data)
- [WIKI Prices on Kaggle](https://www.kaggle.com/datasets/marketneutral/quandl-wiki-prices-us-equites) · [fja05680/sp500, via this write-up](https://riazarbi.github.io/quant/backtesting-sp500-constituent-history/)
- [fredapi](https://github.com/mortada/fredapi)
- [EDGAR rate limits](https://www.sec.gov/filergroup/announcements-old/new-rate-control-limits)
- [Ken French momentum factor](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library/det_mom_factor.html) · [10 momentum portfolios](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/Data_Library/det_10_port_form_pr_12_2.html) · [Changes in CRSP data](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/Data_Library/changes_crsp.html)
- [AQR TSMOM original paper data](https://www.aqr.com/Insights/Datasets/Time-Series-Momentum-Original-Paper-Data)
- [Chen–Zimmermann, SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3604626)
- [JKP factors](https://jkpfactors.com/)
- [Amit Goyal's data](https://sites.google.com/view/agoyal145)
- [Dacheng Xiu (GKX data)](https://dachxiu.chicagobooth.edu/)
- [Free futures data guide](https://www.quantvps.com/blog/cme-historical-data-complete-guide)

**Papers**
- [Hou, Xue & Zhang, Replicating Anomalies](https://academic.oup.com/rfs/article-abstract/33/5/2019/5236964)
- [Jensen, Kelly & Pedersen, Is There a Replication Crisis in Finance?](https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.13249)
- [Gu, Kelly & Xiu, NBER](https://www.nber.org/papers/w25398)
- [Kelly, Malamud & Zhou, Virtue of Complexity](https://onlinelibrary.wiley.com/doi/full/10.1111/jofi.13298)
- [Moskowitz, Ooi & Pedersen, Time Series Momentum](https://research.cbs.dk/en/publications/time-series-momentum/)

**Multi-agent systems (§11)**
- [Why Do Multi-Agent LLM Systems Fail? (MAST), arXiv 2503.13657](https://arxiv.org/abs/2503.13657)
- [Anthropic, Building effective agents](https://www.anthropic.com/research/building-effective-agents) · [Anthropic multi-agent research system, summary](https://blog.bytebytego.com/p/how-anthropic-built-a-multi-agent)
- [Cognition, Don't Build Multi-Agents](https://cognition.com/blog/dont-build-multi-agents) · [Walden Yan, 2026 update](https://x.com/walden_yan/status/2047054554433462360)
- [LLMs Cannot Self-Correct Reasoning Yet, arXiv 2310.01798](https://arxiv.org/abs/2310.01798)
- [LLM-Modulo, ICML 2024](https://proceedings.mlr.press/v235/kambhampati24a.html)
- [Correlated Errors in LLMs, arXiv 2506.07962](https://arxiv.org/abs/2506.07962) · [Family-conditioned preference in judge panels, arXiv 2609.17857](https://arxiv.org/pdf/2609.17857)
- [Stop Overvaluing Multi-Agent Debate, arXiv 2502.08788](https://arxiv.org/pdf/2502.08788)
- [AgentCoder, arXiv 2312.13010](https://arxiv.org/abs/2312.13010)
- [N-Version Programming with Coding Agents, arXiv 2606.20158](https://arxiv.org/abs/2606.20158) · [Knight & Leveson (1986)](https://www.csc.kth.se/utbildning/kth/kurser/DA2210/vettig13/Seminarier/KnightLeveson.pdf)
- [ChatDev, arXiv 2307.07924](https://arxiv.org/pdf/2307.07924)
- [PaperBench, arXiv 2504.01848](https://arxiv.org/abs/2504.01848) · [Evaluating Sakana's AI Scientist, arXiv 2502.14297](https://arxiv.org/pdf/2502.14297) · [Verification Gap survey, arXiv 2608.05179](https://arxiv.org/abs/2608.05179)
- [TraceDev (traceability-driven multi-agent), arXiv 2607.18886](https://arxiv.org/pdf/2607.18886)
- [Claude Code subagents](https://code.claude.com/docs/en/sub-agents)
- [Agent SDK overview](https://code.claude.com/docs/en/agent-sdk/overview)
- [Agent SDK credit change, paused](https://thenewstack.io/anthropic-agent-sdk-credits/) · [Pause confirmation](https://aicatchup.com/news/claude-agent-sdk-monthly-credit-paid-plans)
- [Claude usage limits](https://support.claude.com/en/articles/11049741-what-is-the-max-plan)
- [Agent frameworks compared, 2026](https://www.spheron.network/blog/langgraph-vs-crewai-vs-autogen-2026/)
- [Local LLMs on Apple Silicon](https://www.promptquorum.com/local-llms/best-models-apple-silicon-2026)

**PDF parsing**
- [Table-extraction benchmark, arXiv 2511.16134](https://arxiv.org/html/2511.16134v2)
- [Open-source PDF-to-Markdown tools compared](https://themenonlab.blog/blog/best-open-source-pdf-to-markdown-tools-2026)
