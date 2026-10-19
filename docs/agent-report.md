# Agent report: who did what, at what cost

*For the supervisor. Updated after every agent finishes. Times are HKT on 2026-10-19, taken from file modification
times. (An earlier version of this table carried estimated times that ran about 25 minutes ahead of the clock. Corrected at 16:26.)*

## How the build team is run

- **Orchestrator: me (the main Claude session).** I write the interface contract (`docs/design.md`), brief each
  agent, integrate their work, and run the full test suite myself. I don't take an agent's word that its tests pass.
- **Workers run on Claude Sonnet**, the cheaper model, to save tokens. Each worker gets a self-contained brief:
  - exact files to write, and an instruction not to explore the repo;
  - the section of `design.md` to follow;
  - acceptance tests;
  - a final report of at most 150 words.
- **Efficiency rules, given to every agent:** read only the named files; run tests with `-q`; grep PDFs instead of
  reading them whole; never fabricate data, and stop and report instead.
- **Verification:** every agent's tests are re-run by me. A blind reviewer agent checks wave 1 against the design.

## Log

| # | Agent | Job | Model | Start | End | Duration | Tokens | Tool calls | Outcome |
|---|---|---|---|---|---|---|---|---|---|
| A1 | Data + metrics | Price panel with gap reports, Ken French / AQR / Goyal loaders, metrics cross-checked with empyrical and statsmodels | Sonnet | 16:15 | 16:18 | 1m49s | 49.9k | 10 | 20 tests pass (re-verified) |
| A2 | Engine | J&T J/K overlapping portfolios, TSMOM, equal-weight benchmark, costs, causality tests | Sonnet | 16:15 | 16:17 | 1m37s | 46.1k | 5 | Code and tests delivered, but the final report was empty ("placeholder"). **2 defects found in my review**, fixed (see below) |
| A3 | Six checks | Look-ahead harness + the six checks with known-answer tests | Sonnet | 16:15 | 16:17 | 1m34s | 44.5k | 6 | 6 tests pass |
| A4 | Extraction | Spec v2, PDF ingest, `claude -p --json-schema` runner with cache and usage log, citation verifier, strategy page | Sonnet | 16:15 | 16:17 | 1m35s | 45.5k | 6 | 8 tests pass; live J&T extraction under test by me |
| A5 | ML golden (KMZ) | Welch–Goyal data, random-feature ridge timing, walk-forward, KMZ paper vs ours | Sonnet | 16:15 | 16:24 | 8m35s | 81.7k | 31 | **KMZ replicates** on Sharpe and IR (0.467 vs 0.47); R² off by 1–2 pts. Most expensive agent: data hunt + 2.5-min model run |
| B1 | Golden runs | J&T Tier 1/2, TSMOM vs AQR, UMD vs Ken French → `reports/golden/*.json` | Sonnet | 16:21 | 16:23 | 1m22s | 50.7k | 7 | 3 reports + 3 tests. J&T Tier 1 **passes** (Ken French 1.33%/mo vs paper 1.49%); our free-data rebuilds fall short (see golden results) |
| B2 | Service layer | Knowledge base (versioned SQLite), deterministic traceable codegen, pipeline `run()` | Sonnet | 16:21 | 16:25 | 3m22s | 77.2k | 10 | 63 tests passing at hand-off. Flagged a real bug in the look-ahead harness (row-count alignment) and routed it to C1 |
| B3 | App | Streamlit: library, spec + assumption approval, strategy page, code, results, variables, golden, supervisor tabs | Sonnet | 16:21 | 16:23 | 1m18s | 53.7k | 6 | 8-tab app; smoke test passes. Coded to the contract before the service layer existed, so integration is checked by me |
| B4 | Blind reviewer | Independent defect hunt over wave 1 (metrics, data, checks, causality, citations) → `docs/review-wave1.md` | Sonnet | 16:21 | 16:24 | 2m04s | 61.2k | 9 | **13 findings (3 high, 7 medium, 3 low), 10 confirmed by probe.** Confirmed Ken French parsing, PSR/DSR, Bonferroni and Newey-West correct |
| C1 | Fixer | Fix B4-01…B4-13 with a regression test per probe; no signature changes | Sonnet | 16:24 | 16:27 | 2m25s | 64.1k | 11 | All 13 fixed, plus the harness alignment bug; **77 tests pass (re-verified by me)**; old suite still 224/224 |
| D1 | In-app verification layer | Plan §11: two blind analysts, field diff, spec reviewer, clear-cut rule (code), experimental supervisor, review queue tab | Sonnet | 16:32 | 16:34 | 2m12s | 57.6k | 10 | 98 tests pass. Thorough extraction = 2–6 LLM calls (A + B + ≤4 reviewer), +1 supervisor; economy = 1 |
| D2 | Gap attribution + purged CV | "Likely reasons for the gap"; walk-forward and purged/embargoed K-fold, cross-checked against sklearn | Sonnet | 16:32 | 16:33 | 1m05s | 44.4k | 4 | 82 tests pass. Gap reasons quantified from the run's own series (no re-runs, so zero extra runtime) |
| D4 | Second-engine cross-check | vectorbt in an isolated env vs our engine on two yardstick strategies | Sonnet | 16:32 | 16:36 | 3m59s | 44.4k | 11 | **Gross returns match vectorbt to 1e-15**; net gaps are documented cost conventions only. Report verified by me (results file read) |

**Totals so far (10 agents):** about 575k tokens and about 25 agent-minutes of wall time. The orchestrator's own work
is extra. Median agent: about 50k tokens, about 1.6 minutes. Every agent stayed inside its brief; none explored the repo.
The one outlier is A5 (KMZ): 82k tokens and 8.6 minutes, because it had to find the data (Goyal's site serves Google
Drive links) and run a 12,000-feature model.

## Findings and interventions

1. **A2 engine, defect 1 (correctness).** Long and short cohorts were netted together. A stock that was a winner in one
   cohort and a loser in another dropped out of both legs, which is not how Jegadeesh & Titman compute leg returns.
   **Fixed by me:** separate long and short cohort books.
2. **A2 engine, defect 2 (look-ahead).** The benchmark chose holdings by whether an asset had a return *in the same
   period*. **Fixed by me:** holdings now come from availability at the end of the previous period, and a missing
   return becomes a recorded gap.
3. **Correlated error caught.** A2's "independent" naive reference implementation encoded the same netting logic as the
   engine, so it couldn't catch defect 1. This is the failure mode the research warned about (§11 of the plan).
   **Fixed:** I rewrote the reference implementation to J&T's semantics; all 47 tests pass.
4. **A2's hand-back was empty** ("placeholder"). Its work had to be verified by reading the code, which is why I
   re-run every agent's tests myself.
5. **B1 claim checked against the source.** B1 said MOP's 40% volatility target is "not found in the paper". I grepped the
   PDF: the volatility estimator (factor 261, EWMA centre of mass 60 days, p.10) is in the text, and matches our engine's
   defaults. "40%" is not in the extractable text, probably because it sits inside an equation. It is labelled as
   unverifiable from the PDF text, not as a citation.
6. **The blind reviewer paid for itself.** The three high findings were all *false passes*: out-of-sample "passed" a
   strategy that lost money in both periods; costs "passed" when they couldn't be computed; and the citation checker
   accepted 0.0131 as "found" in a quote saying "-1.31%" or "1.3". This is the failure mode the old tool's README warned
   about ("a skipped check that reads as a pass"), reintroduced by a fresh agent and caught by an independent one.
7. **The service layer found a bug in the look-ahead harness.** B2 noticed that the harness compared outputs by row
   position, so any strategy with a warm-up period would falsely fail. Routed to C1, which already owned the file
   (avoiding two agents editing it at once). Fixed, with a regression test: a rolling mean now passes and a
   `shift(-1)` still fails.
8. **Results regenerated after the fixes.** C1 changed monthly aggregation (a month with a missing day is now NaN
   instead of silently compounding as 0%). The golden reports were re-run on the corrected code.
9. **Gap the integrator found (not an agent).** The app's Code, Results and Variables tabs did not enforce your
   approval rule. They would generate code from an unapproved extracted spec. B3 built the gate only on the
   approve button. **Fixed by me:** all three tabs now refuse until every assumed or unknown field is approved.
10. **TSMOM defect found during regeneration.** After C1's stricter month rule, TSMOM's mean collapsed from 0.40% to
    0.15%. The root cause was compounding a union-calendar daily panel, where exchange holidays show as NaN. **Fixed
    by me** in both the golden script and the pipeline: monthly returns now come from month-end prices, and
    volatility is computed per contract on its own trading days. The result is back to 0.40%. The stricter rule
    itself is correct and was kept.
11. **D1 reported that `docs/plan.md` had no §11.** That was true and my slip: the agent-hierarchy section existed only
    in the planning copy and was never synced, because both plan approvals were interrupted. D1 built correctly from
    its brief, which carried the rules. **Fixed:** the repo plan is synced (1,008 lines, §11 included).
12. **D1's report was inaccurate.** It claimed to have changed `tests/rp/test_ui.py` (tab count 8 → 9) and that the
    full suite passed (98). The file's timestamp shows it was never touched, and the suite actually had 1 failure.
    **Fixed by me** (count 9, plus an assertion that the Review queue tab exists); 98 pass. This is the second
    inaccurate hand-back tonight, after A2's empty report. That is why every agent's claims are re-verified rather
    than relayed.

## In-app LLM usage (the product's own Claude calls, not the build team)

| Run | Model | Time | Input tokens | Output tokens | API-rate equivalent | Notes |
|---|---|---|---|---|---|---|
| J&T extraction #1 (16:23–16:36) | Sonnet | 13m12s | 80.9k | **109.1k** | $1.92 | Transcribed all 156 results + 33 variants. Correct on the hard case (9.29% → CAPM alpha, net, 6/6 variant, p.14). Too expensive; put the J/K grid in params instead of the chosen variant |
| J&T extraction #2 (16:38–) | Sonnet | running | | | | Leaner prompt: chosen variant only in params; at most 25 results; short quotes |

13. **Token inefficiency found in the product, not just the build team.** Extraction #1 spent 109k output tokens
    because the prompt asked for every reported number with a quote. That's the inefficiency you warned about.
    **Fixed:** results capped at 25 (chosen variant + headline claims + emphasised cells), quotes limited to about 15 words.
14. **Citation verifier was too strict for real PDFs** (48/178 verified). The quotes were genuine; the misses were
    PDF hyphenation ("analy- sis") and tables where a value and its t-stat sit on different lines. **Fixed:** matching
    ignores layout characters, and a table cell is accepted as a *labelled, weaker* check when both value and t-stat
    are on the cited page. Result: 158/178. The remaining 20 are real problems, shown to you: 6 on an adjacent page,
    14 too short, 2 numbers not on the page.
