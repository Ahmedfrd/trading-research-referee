# The Replication Referee — Full Project Plan

**Polymer Tech Expo 2026 · Submission deadline 23 August 2026**

---

## 1. What is actually being graded

Before anything technical, be clear about what this competition rewards, because it changes every decision downstream.

| Item | Detail |
|---|---|
| Deliverables | A video of **7 minutes maximum**, plus a **1-page PDF** |
| Deadline | **23 August 2026** |
| Event | 10 September 2026, M+ Museum, Hong Kong |
| Run by | Polymer Capital Management — an **Asia-focused hedge fund**, not a tech company |
| Prizes | HKD 50,000 across the top 4 videos; **up to 20 summer internships** |
| Stated criteria | "Curiosity, creativity, problem-solving ability, and passion for technology" |
| Explicitly stated | **Projects need not be finished. Prototypes and proofs-of-concept are acceptable.** Clear explanation of the AI application matters most |

**The consequence:** the video is the deliverable. The code is the evidence behind it. A prototype that is clearly explained beats a finished product that is badly explained. Budget time accordingly — a full day for the video is the minimum, not a luxury.

**The audience matters too.** These are professional investors. They read backtests every week and their default posture toward "look how much money this made" is scepticism, not admiration. This shapes the entire positioning of the project.

---

## 2. The product

**The Replication Referee** — a tool that takes a published trading-strategy research paper and answers one question:

> **Does the claimed edge survive contact with reality?**

The user uploads a paper. The system reads it, extracts the strategy into a structured specification, generates code from that specification, runs the backtest, and then subjects the result to a battery of audits designed to detect the specific ways backtests lie. The output is a verdict: **REPLICATES / WEAKENED / FAILS**, with the numbers behind it.

### Why this positioning, and not "find profitable strategies"

Because showing profits to a hedge fund loses. If the demo ends with *"our AI-generated strategy beat the market by 60%"*, the room assumes overfitting and discounts everything else. You cannot win these judges by claiming returns.

Inverting it solves the problem entirely. When the product's job is to *debunk*, the demo cannot be accused of being too good to be true — being sceptical is the point. It is also, unlike a backtesting engine, a thing nobody has built.

**Jargon:** *Overfitting* is tuning a strategy until it fits historical data beautifully, at which point it has memorised the past rather than learned anything general, and it dies in live trading. *Backtest* means running a strategy on historical data to see what it would have made.

### The evidence that this problem is real

These belong in the 1-page PDF:

- **Hou, Xue & Zhang** tested **447** published market anomalies. **64% were statistically insignificant** at the conventional 5% level. At the stricter t > 3 threshold, **85%** failed.
- **McLean & Pontiff** tracked **97** published return predictors. Returns were **26% lower** when retested on fresh data, and **58% lower** after publication.

In plain terms: **most published trading research does not work as advertised.** Verifying a single paper by hand takes a skilled analyst one to two weeks. That is the problem being solved.

---

## 3. How it works — the pipeline

```
   PDF upload
        ↓
 ┌──────────────────┐
 │ 1. EXTRACT       │  Claude reads the paper → structured Strategy Spec (YAML)
 └──────────────────┘   Every field carries the sentence it came from
        ↓
 ┌──────────────────┐
 │ 2. HUMAN CONFIRM │  User reviews and corrects the spec before any code exists
 └──────────────────┘
        ↓
 ┌──────────────────┐
 │ 3. GENERATE      │  Spec → Python. Generated from the spec, never the raw PDF
 └──────────────────┘
        ↓
 ┌──────────────────┐
 │ 4. RUN (sandbox) │  Isolated, no network, time limit
 └──────────────────┘
        ↓
 ┌──────────────────┐
 │ 5. AUDIT         │  Six checks — this is the actual product
 └──────────────────┘
        ↓
    VERDICT CARD
```

### Step 2 deserves special attention

The human confirmation step is not a compromise — it is a design statement. It says: *AI misreads papers, I know it, and I built for it rather than hoping.* Most student projects hide their AI's fallibility. Showing yours, and showing the guard rail you built around it, reads as engineering maturity.

### Why the spec sits in the middle

Generating code directly from a PDF gives you no way to check whether the AI understood the paper. Inserting a structured spec gives you **three representations of the same strategy — the paper's English, the spec, and the code — which must all agree.** Disagreement is a detectable bug. That is the whole reason the middle layer exists.

---

## 4. The audit layer — the differentiator

Six checks. Each one targets a specific, well-documented way that backtests mislead.

**1. Look-ahead bias detection**
*Look-ahead bias* is when a backtest uses information that did not exist yet — for example, deciding to buy at Monday's open based on Monday's closing price. It is the most common way backtests lie, and AI-generated code introduces it constantly. The engine enforces a strict signal-to-execution lag, and the auditor re-runs with future data blinded to prove no leakage.

**2. Transaction cost sensitivity**
Real trading costs money: commissions plus *slippage* (you do not get the exact price you wanted). Most published strategies ignore this. The tool sweeps across cost levels and shows the curve — at what cost does the edge disappear?

**3. In-sample vs post-publication split**
*In-sample* is the period the paper tested. *Out-of-sample* is everything after publication, which the authors could not have seen. A strategy that works only in-sample was probably curve-fitted.

**4. Parameter sensitivity**
Does it work only at exactly a 14-day lookback, or across 10–20? The tool sweeps the range and shows the distribution. A real effect looks like a broad plateau; a fluke looks like a single spike.

**5. Multiple-testing counter**
Every variant tested is counted, and the statistical bar rises accordingly. Test one variant, you need normal evidence. Test fifty, you need much more — because with fifty tries something will look good by luck alone. **The tool literally gets harder to please the more the user fiddles with it.** This is the feature nobody else will have.

**6. Cross-engine agreement**
The same spec is run through our engine and through Vibe-Trading. If two independently written backtests of the same strategy disagree, at least one is wrong.

---

## 5. Two modes, deliberately separated

| | **Replication mode** | **Robustness mode** |
|---|---|---|
| Parameters | Locked to the paper's own values | User varies asset, lookback, parameters |
| Output | The verdict on the paper's claim | The full distribution across variants |
| Purpose | Fidelity | Stress testing |

**Why the separation is essential.** If a user can freely change settings and gets one number back each time, they will spin the dials until something looks good and screenshot it. That is overfitting — and it would mean building the exact machine this product exists to detect.

The fix: robustness mode never returns a single result. It sweeps and reports the whole distribution. The question changes from *"which setting is best?"* to *"does this work across settings, or only at one lucky number?"*

---

## 6. Universes and data

| Universe | Source | Notes |
|---|---|---|
| US equities, daily | yfinance (free) | Primary. The replication literature is US-equity based, so results can be checked against published numbers |
| Commodity futures | yfinance (free) | ~24 liquid contracts. Native to the Time Series Momentum paper |
| Crypto | ccxt (free) | Robustness mode only — see below |
| HK / Asia equities | yfinance | Stretch goal. On-brand for Polymer |

### The transferability check

Strategies come in two structural types, and this determines where they can be tested:

- **Time-series** strategies look at one asset at a time (*is gold above its 200-day average?*). These transfer anywhere.
- **Cross-sectional** strategies rank a large group and buy the top / short the bottom (*of 500 stocks, buy the best 50*). These need breadth. There are only ~24 liquid commodities — you cannot rank 24 things into meaningful deciles.

The tool detects the type from the spec and **refuses with a reason** when the universe cannot support the strategy: *"This strategy ranks a cross-section and requires ≥100 assets. Commodities universe has 24. Not testable here."*

A tool that knows its own limits is more credible than one that silently produces a meaningless number.

### Why crypto is robustness-only

Crypto history is short (most coins post-2017), dead coins vanish from the data so backtests silently include only survivors, and there is essentially no academic replication literature. So "does this paper replicate in crypto" is not a well-formed question. But **"this effect was documented in US stocks — does it also appear in crypto?"** is legitimate and interesting. That is a robustness test, and it belongs in robustness mode.

---

## 7. The three test papers

These are the **regression test suite**, not the product. They are chosen because their answers are independently known, so they prove the tool works.

| Paper | Expected verdict | Which audit check it demonstrates |
|---|---|---|
| **Cross-Sectional Momentum** — Jegadeesh & Titman (1993) | FAILS (post-publication) | Engine correctness; validated vs AQR US momentum |
| **Short-Term Reversal** — de Groot, Huij & Zhou results | DIES ON COSTS | Cost sensitivity sweep |
| **Technical Trading Rules** — Brock, Lakonishok & LeBaron (1992) | DIES ON DATA-SNOOPING | Multiple-testing counter |

Three papers, three distinct failure modes, three features demonstrated. The demo arc writes itself: *this one is real; this one is real but untradeable; this one was never real.*

> **Revised 19 Aug 2026 — Paper 1 swapped.** TSMOM scoped to commodities proved
> a weak anchor: free futures data covers only 21 of the paper's 58 contracts,
> and Yahoo's continuous contracts stitch months together without
> back-adjustment, depressing the result. Candidates were tested rather than
> assumed — cross-sectional momentum correlated **0.712** with AQR's published
> US momentum factor over **652 months** (vs 0.680 / 331 for TSMOM), while the
> low-volatility anomaly scored **−0.55** and was rejected. **Jegadeesh &
> Titman (1993)** is now the primary validation paper. TSMOM remains as a
> second reference case and its AQR test stays in the suite.
>
> Its verdict is **WEAKENED**, not REPLICATES: the effect is real (t=2.90,
> survives 20bps, broad parameter plateau) but **decayed 80% after
> publication** — the McLean & Pontiff result, measured on the canonical
> anomaly. That is a stronger demonstration than a clean pass.

### Paper 1 gives us free engine validation

Moskowitz, Ooi & Pedersen covers 58 liquid futures across equity indices, currencies, **24 commodities**, and bonds. The signal is trivially simple: if an asset's past 12-month return was positive, go long; if negative, go short. Reported Sharpe ratio above 1.0.

(*Sharpe ratio* = return per unit of risk. The stock market itself is around 0.4; above 1.0 is very good.)

**AQR publishes the original paper's monthly returns for free** as an Excel file covering January 1985 to December 2009. This means the engine can be validated against the original authors' own published numbers — the gold standard, available at zero cost. This is what makes every later claim credible.

### Paper 2 is the demo's best 30 seconds

Short-term reversal: buy last week's losers, short last week's winners, rebalance weekly. Published results, in basis points per week (1 bp = one hundredth of one percent):

| Universe & construction | Gross | Net of costs |
|---|---|---|
| 1,500 largest stocks, standard | +61.7 bps | **−103.7 bps** |
| 500 largest, careful construction | +65.0 bps | +30.5 bps |
| 100 largest, careful construction | +77.9 bps | +53.1 bps |

The first row flips sign entirely — from strongly profitable to catastrophically loss-making — **purely from trading costs**. The other rows show the same anomaly surviving when implemented carefully. This is the entire thesis in one table, and it can be demonstrated live by dragging a cost slider until the verdict flips.

### Paper 3 is the intellectual ancestor

Brock, Lakonishok & LeBaron tested 26 technical trading rules and found they worked. Sullivan, Timmermann & White (1999) re-examined the result across the full universe of rules those 26 were drawn from, on 100 years of Dow data, explicitly measuring data-snooping bias. That is this project's thesis, published in the *Journal of Finance* in 1999.

**Outstanding item:** the full conclusions sit behind a paywall. The specific numbers must be verified from the full text before they appear in the PDF.

---

## 8. Technical stack

| Layer | Choice | Reasoning |
|---|---|---|
| Language | Python 3.11+ | Data ecosystem |
| Interface | Streamlit | Native tabs, file upload, syntax-highlighted code display, and charts in hours rather than days. Looks like a prototype — which the rules explicitly permit |
| AI | **Claude API** (Messages API with structured outputs) | Not the CLI — see below |
| Backtest | Own engine (pandas/numpy) | Must be explainable and defensible |
| Cross-check | Vibe-Trading (HKUDS) | Independent second opinion |
| Data | yfinance, ccxt | Free, no API keys |
| Storage | SQLite | Single file, no server, built into Python |
| Charts | Plotly | Interactive, screen-records well |

### Why the API and not the Claude CLI

Three reasons. **Structured outputs** guarantee the spec comes back matching the schema, instead of parsing free text. **Determinism and speed** — no shell orchestration, no interactive session to babysit. And most importantly, the submission explicitly asks you to show **"system prompts (with examples)"** — an architecture built on explicit, versioned system prompts is directly aligned with what is being graded. Shelling out to a CLI hides exactly the thing the judges asked to see.

### Sandboxing

Generated code is executed in a subprocess with no network access, a restricted import set, and a hard timeout. Full isolation would require Docker; if time runs short, the honest position is to state the limitation rather than overclaim it.

---

## 9. The backtest engine — the correctness checklist

The goal is not "minimal" and not "best". It is **correct**. Nine requirements, each with a test:

1. **No future data** — nothing uses information from after the decision point
2. **Realistic execution lag** — signal on Monday's close, trade at Tuesday's open
3. **Transaction costs** — commission and slippage, adjustable
4. **Position sizing** — as the paper specifies (equal weight, volatility-scaled, etc.)
5. **Correct rebalancing schedule**
6. **Split- and dividend-adjusted prices**
7. **Shorting handled properly** for long/short strategies
8. **Risk statistics** — Sharpe ratio, maximum drawdown, turnover, not just returns
9. **A validation suite** — including reproduction of AQR's published TSMOM series

The resulting video line: *"My engine is deliberately small. Every component is tested against a known result — because a tool that audits other people's backtests has no business shipping an unaudited one."*

---

## 10. Five-day schedule

| Day | Focus | Output |
|---|---|---|
| **Tue 18 Aug** | Papers locked, data pipeline, Strategy Spec schema | Spec schema finalised, data loading for all three universes |
| **Wed 19 Aug** | Backtest engine + validation against AQR data | Engine passing its test suite |
| **Thu 20 Aug** | AI layer: PDF → spec → confirm → code → sandboxed run | End-to-end pipeline working on one paper |
| **Fri 21 Aug** | Audit layer — **protect this day** | Six checks + verdict card |
| **Sat 22 Aug** | UI, tabs, database, cross-engine check, **record video, write PDF** | Submission-ready |
| **Sun 23 Aug** | Buffer and submit. **Do not plan to build** | Submitted |

### Cut list — decided now, calmly, not at midnight on Saturday

Drop in this order if behind:

1. Vibe-Trading cross-check
2. Web UI (fall back to command line plus good charts)
3. Third test paper
4. Parameter sweep

**Never cut:** the look-ahead bias check, the out-of-sample split, and the video day.

---

## 11. Honest limitations — state these out loud

Naming your own weaknesses before a judge finds them converts them into evidence of rigour.

- **Survivorship bias.** Free data provides *today's* index members, not historical membership. Backtests therefore silently include only companies that survived, which flatters every result. There is no clean free fix.
- **Papers requiring data we do not have.** Strategies built on accounting data, order-book data, or proprietary datasets cannot be tested. The tool should detect this and say so explicitly rather than fabricating a result.
- **Extraction is imperfect.** The AI will misread some papers. The human confirmation step is the mitigation, not a cure.
- **Sandbox is partial** unless Docker gets built.

---

## 12. The general-tool question

**The product is a general tool: upload any paper, and the pipeline runs.** The three papers are the test suite that proves it works, not a hardcoded demo.

But the honest engineering position is that a general tool will fail on a meaningful fraction of papers — some need unavailable data, some describe strategies too vaguely to specify, some are not really about a tradeable strategy at all. The system must **fail loudly and specifically** rather than silently producing a number.

For the demo: show the three known papers first (where the answers can be verified), then upload a fourth paper live to prove generality. Pre-test several candidates so the live upload is a calculated risk rather than a gamble.

---

## 13. Future enhancements — for the PDF

- **A public replication ledger.** As users run audits, the database accumulates a shared record of which published strategies replicate and which do not. This reframes the project from a demo into the beginning of a genuine research resource.
- Asia and HK equity coverage, matching Polymer's own market focus.
- Full Docker isolation for generated code.
- Automated ingestion of new working papers from SSRN and arXiv.

---

## 14. What goes in the video (7 minutes)

| Segment | Time | Content |
|---|---|---|
| Self-introduction | ~1:00 | Personal branding line, AI's impact on your learning, fun fact, career aspiration |
| The problem | ~1:00 | The replication statistics. Verifying one paper by hand takes weeks |
| Live demo | ~3:00 | Upload → spec → confirm → code → verdict. Then the cost slider flipping a verdict live |
| How AI was used | ~1:00 | Claude API, system prompts on screen, the spec-as-contract design, the human confirmation guard rail |
| Reflections | ~1:00 | What worked, what you would improve, stated limitations |

---

## 15. What goes in the 1-page PDF

One page, 11pt minimum, visuals allowed.

- **Problem statement** — the replication crisis, with the Hou/Xue/Zhang and McLean/Pontiff figures
- **Solution overview** — the pipeline diagram plus the verdict card
- **Use of AI** — Claude API, structured extraction, spec-driven generation, sandboxed execution
- **Impact** — weeks of analyst work compressed into minutes; a defence against acting on published results that do not hold
- **Reflections** — the honest limitations, and the public replication ledger as the next step
