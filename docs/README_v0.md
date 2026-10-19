# The Replication Referee

Upload a published trading-strategy paper. Get back one answer:

> **Does the claimed edge survive contact with reality?**

Most published trading research does not work as advertised. Hou, Xue & Zhang
tested 447 published anomalies and found **64% statistically insignificant**
at the 5% level, and **85%** failing at t > 3. McLean & Pontiff tracked 97
return predictors and found returns **26% lower** on fresh data and **58%
lower** after publication. Verifying one paper by hand takes a skilled analyst
one to two weeks.

## The pipeline

```
   PDF
    │
    ▼
1. EXTRACT      Claude reads the paper into a Strategy Spec.
                Every field carries the sentence it came from,
                and every sentence is checked against the text.
    │
    ▼
2. CONFIRM      A human reads the whole strategy in English,
                sees what will compromise the test, corrects
                anything wrong.  ── HARD GATE ──
    │
    ▼
3. GENERATE     Spec → Python, never from the raw PDF. Shown
                beside the spec it implements. A human reads it
                and approves it.  ── HARD GATE ──
    │
    ▼
4. RUN          Isolated subprocess: import allowlist, CPU limit,
                wall-clock timeout, static AST check first.
    │
    ▼
5. AUDIT        Six checks.
    │
    ▼
  VERDICT       REPLICATES · WEAKENED · FAILS · NOT_TESTABLE
```

### Two gates, not one

The static check proves the generated code is *safe* and *causal*. It cannot
prove the code implements the strategy under review — safe code that computes
the wrong thing passes every automated test there is. So a person reads it
against the specification before it runs, and the verdict stays locked until
they do. Regenerating withdraws the approval: it belongs to the code that was
read, not to the session.

One deliberate escape. The audit can be run **without** the cross-engine
check, for when the model is slow or unreachable. It runs five checks instead
of six and says so on the verdict card, because a skipped check that reads as
a pass is worse than no check at all.

### Why the spec sits in the middle

Generating code straight from a PDF leaves no way to check whether the AI
understood the paper — you can only check that the code runs. Inserting a
structured spec gives three descriptions of the same strategy — the paper's
English, the spec, and the code — which must all agree. Disagreement becomes
a detectable bug instead of a silently wrong number.

## What the reviewer actually sees

The confirmation step is the product, so it is not a JSON dump. Stage 2 shows:

- **The entire strategy written out in English** — universe, signal, ranking,
  sizing, timing, costs, and the claim being tested. It is rendered *from the
  spec*, never written by a model, so the prose cannot drift from what will be
  backtested. Assumed and inferred fields are marked inline, in the sentence
  that depends on them.
- **Everything that will compromise the test**, graded. Not only *did we read
  the paper correctly?* but *can we honestly test it with the data we have?* —
  universe shortfall, contracts with no free feed, insufficient history,
  missing pre-publication data, survivorship. Blocking problems are separated
  from ones that merely shape the answer.
- **A correction for every field the paper did not state.** The reviewer can
  overrule the extractor, and the correction is what gets backtested. It is
  recorded in the spec's own notes so a changed parameter travels with the
  verdict. Confidence is deliberately *not* promoted to "explicit" on an edit:
  the paper still does not state it, and laundering a human guess into a
  citation is the exact failure this tool exists to catch.

## The six checks

| Check | Catches |
|---|---|
| Look-ahead bias | Using information that did not exist yet. Blinding test: delete the future, require the past to be unchanged. |
| Transaction costs | Strategies profitable on paper and loss-making when traded. Sweeps the cost curve and finds the break-even. |
| Out-of-sample | Effects that stop working the moment they are published. |
| Parameter sensitivity | Results that need one lucky parameter. A real effect is a plateau; a fluke is a spike. |
| Multiple testing | Every variant tried raises the significance bar. **The tool gets harder to please the more you fiddle with it.** |
| Cross-engine agreement | Our hand-written engine vs the AI-generated code, from the same spec. If two independent implementations disagree, one is wrong. |

Plus a check that runs before any of them: **quote verification**. Every
non-assumed field claims a verbatim sentence from the paper, and the tool
confirms that sentence actually exists. A field citing words nobody wrote is a
fabricated citation, whether an AI or a person produced it — see below.

The verdict names the failure that destroys most of the claim, not whichever
check happened to run first. A strategy that was never statistically
significant leads with that, rather than arguing about its transaction costs.

## Two modes, deliberately separated

**Replication** locks every parameter to the paper's own values and answers
one question. **Robustness** lets you vary settings but never returns a single
number — only the distribution across the whole sweep. If a user could spin
the dials and screenshot the best result, the tool would be a machine for
manufacturing exactly the overfitting it exists to detect.

## Validation

The engine is checked against **AQR's own published factor returns**, from an
independently written implementation:

| Our strategy | Reference series | Months | Correlation |
|---|---|---|---|
| Momentum | Ken French `UMD` (Dartmouth) | 663 | **0.718** |
| Momentum | AQR `MOMLS_VME_US90` | 652 | **0.719** |
| Time-series momentum | AQR `TSMOM^CM` | 331 | **0.680** |
| *AQR vs Ken French* | *two professional providers of the same factor* | *652* | ***0.917*** |

That last row is the context that matters: two well-resourced firms building
the same published factor from full CRSP data agree at 0.917, not 1.0. That is
the realistic ceiling for any independent implementation, and we reach ~80% of
it using 108 survivorship-biased tickers from a free data source.

### Correlation is not magnitude

Correlation says we are measuring momentum. It does not say we are measuring
all of it, and the gap is large enough to change an answer:

| | Sharpe, same 663 months |
|---|---|
| Ken French `UMD`, full CRSP | **0.49** |
| Ours, 108 current large caps | **0.24** |

We track the factor's direction and capture about half its strength. The
missing half is structural rather than a bug: momentum is concentrated in
smaller names and in firms that later failed, which is exactly what a list of
today's survivors leaves out. Widening the list does not fix it — a 487-name
universe tracked `UMD` *better* (correlation 0.769) and scored *lower* (Sharpe
0.13), because the added breadth arrives mostly after 2000, in the years
momentum stopped working.

The consequence is stated plainly because it cuts against our own results:
**a FAILS on an equity paper is partly a statement about this universe.**
Run our own audit arithmetic over Ken French's series and momentum passes both
of the checks our spec fails — t=4.63 against a 1.96 bar, and 53% of its
in-sample Sharpe retained after 1993. Verdicts reached on a fraction of a
paper's cross-section carry that caveat on the card, and
`tests/test_universe_power.py` measures the attenuation rather than asserting
it in prose.

Independent checks on the components:

| Component | Checked against | Result |
|---|---|---|
| Multiple-testing bar | `scipy.stats.norm.ppf` | exact to 1e-12 |
| Sharpe, volatility, hit rate | hand-computed closed forms | exact |
| Max drawdown | hand-computed peak-to-trough | exact, after a fix |
| Price data | CRSP total market (Ken French) | corr **0.944**, vol 16.4% vs 15.8% |

A tool that audits other people's backtests has no business shipping an
unaudited one. **243 tests**, including the causality of every signal kind,
cost accounting, drawdown arithmetic, both AQR reproductions, the Streamlit
interface driven end to end — and a test that the audit is *capable of
passing* a strategy that genuinely works, so it cannot silently become a
machine that always says no.

## What the papers show

Measured, not intended. Every number below comes from a run on the data the
tool can actually obtain.

**Reference papers** — hand-written specs, independently known answers:

| Paper | Verdict | Leading reason | Shape of the result |
|---|---|---|---|
| Jegadeesh & Titman (1993) | **FAILS** | t=0.73 vs 1.96 | Sharpe 0.10 net; also decays after publication (0.35 → −0.07). Tested on 11% of the paper's universe — read with the caveat above |
| Time-series momentum (2012) | **FAILS** | t=1.16 vs 1.96 | Passes the other four checks outright. Sharpe 0.22 against AQR's own far stronger series; roll gaps are the gap |
| Short-term reversal | **FAILS** | Edge gone by 20bps | **Overwhelmingly real and untradeable**: t=9.69, gross Sharpe 1.29, 90x turnover a year |
| Technical trading rules (1992) | **FAILS** | t=0.28 vs 1.96 | Sharpe 0.05. Never distinguishable from luck; dead at 5bps besides |

**Real papers**, extracted by the pipeline from PDF:

| Paper | Verdict | What it shows |
|---|---|---|
| *Physical approach to price momentum* (arXiv 1208.2775) | **WEAKENED** | t=4.91, Sharpe 0.65, +8.3%/yr — and 41x turnover eats all of it. In-sample 0.78 → 0.11 after publication |
| *Reward-risk momentum* (arXiv 1403.6093) | **FAILS** | t=−0.17 |
| *Spatio-Temporal Momentum* (arXiv 2302.10175) | **FAILS** | t=0.14 |
| *Physical Momentum, Indian market* (arXiv 2302.13245) | **NOT_TESTABLE** | Refused, with the reason named: no universe configured for that asset class |

Three distinct *reasons*, which is the more useful axis than the verdict label:

- **Real but untradeable** — short-term reversal. A t-statistic of 9.69 puts
  the effect beyond argument. It still loses money, because it turns over
  ninety times a year and the edge is gone by twenty basis points.
- **Never real** — technical trading rules. t=0.28. There is nothing here to
  trade at any cost level.
- **Real but decayed** — *Physical approach to price momentum*. Significant,
  genuine, and most of it gone by the time you have paid to trade it.

**No paper currently returns REPLICATES.** That is a property of the universe
rather than of the literature — see *Correlation is not magnitude* — and the
honest thing is to say so rather than to hunt for a construction that passes.

## Running it

```bash
python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/streamlit run app.py
```

Opens at `http://localhost:8501`. Stop it with `Ctrl+C`.

The AI layer shells out to the Claude Code CLI (`claude -p`), so it needs no
API key. The backend sits behind a `Protocol`, so swapping to the Messages
API is one class. Opus is the default: extraction is the step everything
downstream inherits its errors from.

Extraction takes about **three minutes** on a full paper, so a spec already
produced for the same PDF is reused rather than re-bought — 183s becomes
0.8s. The reuse is stated on screen rather than implying a fresh reading, and
**quotes are re-verified against the document every time**, cached or not, so
a stale spec cannot pass unnoticed.

```bash
.venv/bin/pytest                # 243 tests
.venv/bin/pytest -m "not slow"  # skip the ones that load real price history
```

## The verifier caught its own author

The reference specs were originally hand-written, on the assumption that a
human transcribing a paper is more trustworthy than an AI reading one. When
the real Jegadeesh & Titman PDF was finally run through the pipeline, the
comparison was not close:

| Spec for the same paper | Quotes verified against the text |
|---|---|
| Hand-written by the author | **31%** — 9 of 13 quotes did not exist |
| Extracted by Claude | **100%** — 0 of 12 fabricated |

The human had paraphrased from memory: a cited cost assumption of *"returns
are reported before transaction costs"* appears nowhere in the paper, which in
fact reports a 9.29% annual return net of a 0.5% one-way cost. Three
parameters were wrong as a result.

Quote verification now runs automatically after extraction, and a test asserts
the shipped reference spec stays at 100%. The lesson is the project's own
thesis applied to itself: **do not trust a claim because of who made it —
check it against the source.**

## Bugs the verification passes found

Validating against external sources surfaced three real defects:

1. **Max drawdown ignored your starting capital.** The equity curve began at
   the first return rather than at 1.0, so a strategy losing money from day one
   measured its drawdown from an already-depressed peak: −10% then −10%
   reported −10%, not the −19% you were actually down.
2. **Zero volatility zeroed every statistic.** A degenerate-input guard fired
   on `std == 0` and blanked return, drawdown and hit rate along with Sharpe —
   reporting a steadily losing strategy as flat.
3. **Long/short legs were not balanced.** Percentile thresholds gave the long
   leg 11 names and the short leg 10 out of 108: a persistent ~5% net long
   position in a supposedly market-neutral book, worth **+0.9%/yr of borrowed
   equity beta** against a +3.1% gross strategy return. Nearly a third of the
   reported "momentum profit" was market exposure. Fixing it *raised*
   correlation with both reference factors, which is the confirmation that it
   was a real bug.

A later pass, driven by the question *"why does nothing ever replicate?"*,
found five more:

4. **The out-of-sample check reported decay that had not happened.** Retention
   was hard-coded to zero whenever in-sample Sharpe was non-positive, so a
   strategy that lost money in the paper's own window and made money afterwards
   was reported as *"Decayed 100% after publication… substantially weaker than
   advertised"*. One shipped paper hit this exactly: in-sample −0.02,
   out-of-sample **+0.85**. Losing in both periods is now named for what it is
   rather than dressed up as decay, and an improvement is no longer a failure.
5. **A minimum-history guard was applied on only one side of the split.** The
   check required a year of post-publication data and nothing at all before it.
   Brock, Lakonishok & LeBaron published in 1992 and our Dow history starts in
   January 1992, so a Sharpe computed from **54 days** was published on the card
   as a 100% decay finding.
6. **A percentage return was taken across zero.** WTI settled at **−$37.63** on
   2020-04-20. `pct_change` across that sign flip produced a −306% day and a
   +127% day — two moves larger than anything that happened — and inflated
   crude's measured volatility to 77% against Brent's 38% for the same
   commodity. Non-positive marks are now dropped and the drop recorded.
7. **A rate limit was cached as a delisting.** One throttled download wrote
   *"possibly delisted"* markers for **354 live companies**, and the loader
   honours those for seven days. A universe that quietly loses names is the
   precise failure this module claims to prevent. A request that fails now
   leaves the negative cache untouched.
8. **The verdict led with the wrong reason.** The one-line explanation was
   whichever check happened to fail first in list order, so a strategy with a
   t-statistic of **0.28** was reported as *"edge disappears at 5 bps"* —
   arguing about trading costs for an effect that was never distinguishable
   from luck. Failures are now ranked by how much of the claim they destroy.

And one that the fix for #4 introduced, caught before it shipped:

9. **A nullable field reached a format string.** Splitting the out-of-sample
   check left `retained` unset on the "no edge in either period" branch, which
   is still an *applicable* check — and the verdict card renders a delta from
   that field for any applicable check. The tab raised `TypeError` on exactly
   the papers the fix was written for. The interface had no test coverage at
   all, which is how a data-contract change reached the screen; it now has
   `tests/test_app.py`, which drives the real UI through its own buttons.

## Stated limitations

- **Survivorship bias, and the attenuation it causes.** Free data gives
  *today's* index members, not historical membership, so backtests silently
  include only survivors. Measured against Ken French's UMD, this costs about
  **half the Sharpe** of the effect being tested — enough to turn a real
  result insignificant. There is no clean free fix, and widening the ticker
  list makes it worse rather than better (see *Correlation is not magnitude*).
  Verdicts reached on a fraction of a paper's universe say so on the card.
- **No paper in the corpus currently returns REPLICATES.** Given the point
  above, that is a fact about the data rather than a discovery about the
  literature, and it should not be presented as one.
- **The schema is narrow, deliberately.** The controlled vocabularies express
  1,152 combinations, and the space of published strategies is not bounded.
  Four of five real arXiv papers reported a mismatch: an R-ratio from an
  ARMA-GARCH model, the output of a Sharpe-optimised neural network,
  mass-weighted momentum, an Indian equity universe. The extractor records
  each as a schema mismatch rather than approximating quietly, and the gate
  refuses what it cannot express — but *refusing* is not the same as
  *covering*. The next step is generating the signal while keeping the
  execution machinery fixed, which widens coverage without giving up
  look-ahead control.
- **Futures roll gaps.** Yahoo's continuous contracts stitch months together
  without back-adjustment. This depresses our measured Sharpe against
  properly roll-adjusted series, and is why our TSMOM number sits below AQR's.
- **Partial sandbox.** Generated code runs in an isolated subprocess with an
  import allowlist and resource limits, not a container. Proportionate to the
  threat of *wrong* AI code; not proof against a hostile attacker.
- **Extraction is imperfect.** The AI will misread some papers. The human
  confirmation step is the mitigation, not a cure.
- **Papers needing data we do not have** — accounting data, order-book data,
  proprietary datasets — are refused with a reason rather than approximated.

## Layout

```
referee/
  spec.py          the Strategy Spec: the contract between paper and code
  papers.py        four reference papers with independently known answers
  describe.py      the spec written out in full English, for the reviewer
  feasibility.py   everything that will compromise a test, graded
  data/            universes and cached price loading
  engine/          backtest engine and the execution sandbox
  ai/              LLM client, extraction, code generation, static checks
  audit/           the six checks and the verdict
  pipeline.py      the five stages, and the two human gates
prompts/           versioned system prompts, shown in the UI
tests/             243 tests, including the UI driven end to end
app.py             Streamlit interface
```
