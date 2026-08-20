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
                Every field carries the sentence it came from.
    │
    ▼
2. CONFIRM      A human reviews the spec before any code exists.
                Assumptions are shown first. This is a hard gate.
    │
    ▼
3. GENERATE     Spec → Python. Generated from the reviewed spec,
                never from the raw PDF.
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

### Why the spec sits in the middle

Generating code straight from a PDF leaves no way to check whether the AI
understood the paper — you can only check that the code runs. Inserting a
structured spec gives three descriptions of the same strategy — the paper's
English, the spec, and the code — which must all agree. Disagreement becomes
a detectable bug instead of a silently wrong number.

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
| Momentum | Ken French `UMD` (Dartmouth) | 652 | **0.738** |
| Momentum | AQR `MOMLS_VME_US90` | 652 | **0.729** |
| Time-series momentum | AQR `TSMOM^CM` | 331 | **0.680** |
| *AQR vs Ken French* | *two professional providers of the same factor* | *652* | ***0.917*** |

That last row is the context that matters: two well-resourced firms building
the same published factor from full CRSP data agree at 0.917, not 1.0. That is
the realistic ceiling for any independent implementation, and we reach ~80% of
it using 108 survivorship-biased tickers from a free data source.

Independent checks on the components:

| Component | Checked against | Result |
|---|---|---|
| Multiple-testing bar | `scipy.stats.norm.ppf` | exact to 1e-12 |
| Sharpe, volatility, hit rate | hand-computed closed forms | exact |
| Max drawdown | hand-computed peak-to-trough | exact, after a fix |
| Price data | CRSP total market (Ken French) | corr **0.944**, vol 16.4% vs 15.8% |

A tool that audits other people's backtests has no business shipping an
unaudited one. **84 tests**, including the causality of every signal kind,
cost accounting, drawdown arithmetic, both AQR reproductions — and a test
that the audit is *capable of passing* a strategy that genuinely works, so it
cannot silently become a machine that always says no.

## What the reference papers show

| Paper | Verdict | Why |
|---|---|---|
| Jegadeesh & Titman (1993) | **FAILS** | Survives look-ahead, costs and parameter sweeps, but **stopped working after publication**: Sharpe 0.55 in-sample, −0.02 after 1993 |
| Short-term reversal | **FAILS** | Overwhelmingly real (t=10.20, gross Sharpe 1.35) and **untradeable**: 90x turnover, edge gone by 20bps |
| Technical trading rules (1992) | **FAILS** | Sharpe 0.05, no edge even before costs, decayed 100% post-publication |

Three distinct failure modes: *real but decayed*, *real but untradeable*,
*never real*.

## Running it

```bash
python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/streamlit run app.py
```

The AI layer shells out to the Claude Code CLI (`claude -p`), so it needs no
API key. The backend sits behind a `Protocol`, so swapping to the Messages
API is one class.

```bash
.venv/bin/pytest              # 84 tests
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

## Bugs the verification pass found

Validating against external sources surfaced three real defects, all now
fixed and covered by tests:

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

## Stated limitations

- **Survivorship bias.** Free data gives *today's* index members, not
  historical membership, so backtests silently include only survivors. There
  is no clean free fix.
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
  papers.py        three reference papers with independently known answers
  data/            universes and cached price loading
  engine/          backtest engine and the execution sandbox
  ai/              LLM client, extraction, code generation, static checks
  audit/           the six checks and the verdict
  pipeline.py      the five stages
prompts/           versioned system prompts, shown in the UI
tests/             84 tests
app.py             Streamlit interface
```
