# Demo run sheet

Measured end to end: **26 seconds** of tool time, zero errors — of which
**17s is the model writing the signal function**. Everything below is timing
for *you talking*, not for the software waiting.

```bash
cd "/Users/ranamuhammadahmed/Desktop/Polymer Tech Project"
.venv/bin/streamlit run app.py
```

Opens at `http://localhost:8501`. Stop with `Ctrl+C`.

## Before you present

1. **Click through the whole path once.** Not to check it works — to check you
   know where the buttons are. Three of them changed names.
2. **Then hit *Reset session*** in the sidebar. The variants counter raises the
   significance bar on every run; demo twice without resetting and your second
   paper is judged against a higher bar than your first, and someone will ask.
3. Leave the sidebar on **Replication**, not Robustness.

## If the model stalls or the network dies

The one failure that can strand you mid-demo is code generation hanging on
tab 3. Rehearse this once:

1. **Stop** — top right of the screen, beside Deploy.
2. Sidebar → Mode → **Replication** (the escape hatch does not exist in
   Robustness mode).
3. Tab **4 · Verdict** → tick **"Run without the cross-engine check"** →
   **Run the audit**.

Five checks instead of six, with the omission printed on the verdict card.
Do not reach for it unless you have to — the cross-engine check is one of the
better things you have to show.

---

## The 3-minute demo

### 0:00 — The problem (~25s)

> Hou, Xue and Zhang tested 447 published market anomalies. **64% were
> statistically insignificant.** At the stricter t > 3 bar, **85% failed.**
> McLean and Pontiff tracked 97 return predictors: returns were **26% lower**
> on fresh data, **58% lower after publication**.
>
> Checking one paper by hand takes an analyst one to two weeks.

### 0:25 — Tab 1, load the paper (~15s)

Select **Cross-Sectional Momentum (Jegadeesh & Titman 1993)** → *Load
reference specification*.

> This is the most-replicated anomaly in finance. Buy last year's winners,
> short last year's losers. If the tool can't handle this one, nothing else
> it says matters.

### 0:40 — Tab 2, the human gate (~40s) — **the most important 40 seconds**

> The AI read the paper into a structured specification. It does **not** get
> to go straight to code.

Scroll the strategy write-up.

> This is the entire strategy in English — universe, signal, how a score
> becomes a position, sizing, timing, costs, and the claim being tested. It's
> generated from the specification itself, not written by a model, so the
> description can't drift from what actually gets backtested.
>
> Green means the paper stated it. Yellow means inferred. **Red means the
> paper never said this and the AI is guessing** — here, the execution lag.
> The paper is silent on it, and it's the single field that decides whether
> the backtest is honest.

Point at the orange problems panel.

> And this is the part most projects would hide. It isn't only asking *did I
> read the paper right* — it's asking *can I honestly test it at all*.
> Jegadeesh and Titman traded the whole NYSE and AMEX. **I have 108 stocks —
> eleven percent of their universe.** The tool says so before it gives me a
> number, not afterwards.

Point at the correction fields.

> And if I disagree with the AI, I change it here, and my correction is what
> gets tested. It's recorded on the specification so the number can be traced
> back to it — and it stays marked as an assumption, because *I* said it, not
> the paper.

Click *I have reviewed this specification*.

### 1:20 — Tab 3, generated code (~35s) — **the second gate**

*Generate code.* (~17s — talk over it.)

> Generated from the reviewed specification — never from the raw PDF. The
> specification is on the left, the code on the right, so you can check them
> against each other line by line.
>
> Then it is checked before it runs: no reading future rows, no imports beyond
> pandas and numpy, no file or network access.

Point at the static-check box, then the approval box below it.

> That green tick proves the code is **safe** and **causal**. It does not
> prove it implements the right strategy — no automated check can. So there's
> a second gate: I have to read it and say it matches. The audit button in
> tab 4 stays disabled until I do.

Click *This code implements the specification — approve and run.*

### 1:55 — Tab 4, the verdict (~50s)

*Run the audit.* (Now enabled, because the code was approved.)

> The most-replicated anomaly in finance. It passes look-ahead testing and it
> survives realistic costs.
>
> And it **stopped working after it was published**. Sharpe **0.35** on the
> years Jegadeesh and Titman studied. **−0.07** on everything since. That's
> McLean and Pontiff's finding, measured live, on the canonical paper.

Point at the claimed-vs-measured table and the dashed line on the chart.

> The paper claimed **9.29% a year**. That dashed line is the advertisement.
> The solid line is what it actually earned. The gap is the product.

Then the coverage note at the bottom of the card, before anyone else does:

> It says FAILS, and I'll tell you why that verdict is only half about the
> paper. Momentum lives in the small names and the ones that went bust —
> exactly what a list of today's survivors leaves out. Run my own audit
> arithmetic over Ken French's proper factor and momentum **passes**. The tool
> prints that caveat itself rather than letting me take credit for a
> harsh-looking result.

Open the **Cross-engine agreement** check.

> Two independent implementations of the same specification — mine written by
> hand, Claude's generated from the spec. They agree 100%, across 1.1 million
> values. If they disagreed, at least one would be wrong, and you should not
> trust the number.

### 2:45 — The cost flip (~30s) — **the money shot**

Reset session → load **Short-Term Reversal** → confirm → generate → approve →
audit.

> Gross Sharpe **1.29**. Sixteen percent a year. t-statistic **9.7** —
> this effect is beyond question real.
>
> And it **fails**. It turns over ninety times a year, and the edge is gone
> by twenty basis points. Real, and untradeable.

Open the **Transaction costs** check to show the curve crossing zero.

---

## If you have another minute

**A second verdict colour.** Tab 1 → Upload PDF →
`data/papers/arxiv_1208.2775v5.pdf` → *Extract specification*. It is
pre-cached, so it loads in about a second rather than three minutes — the
screen says so rather than pretending the model just read it.

> Every reference paper fails. This one comes back **WEAKENED**: a real
> effect, t of 4.9, eight percent a year — and forty-one times turnover eats
> essentially all of it. Real but decayed, rather than never real.

**The refusal.** Upload `data/papers/arxiv_2302.13245v1.pdf`.

> Indian equities. I have no universe for that market, so instead of
> substituting something close and giving you a confident number about a
> different strategy, it refuses — and names the exact reason.

**The multiple-testing counter.** Switch to **Robustness**, sweep, watch the
sidebar counter climb. *(Reset the session afterwards.)*

> Robustness mode never returns one number — only the distribution. And every
> variant you try raises the statistical bar. Test one strategy, you need
> t=1.96. Test twenty-six — exactly how many rules Brock, Lakonishok and
> LeBaron tested in 1992 — you need **t=3.10**.
>
> The tool gets harder to please the more you fiddle with it. That's
> deliberate: a tool that lets you spin dials until something looks good is a
> machine for manufacturing the exact problem it exists to detect.

---

## Numbers to have ready

| Claim | Number |
|---|---|
| Engine vs Ken French UMD | corr **0.718**, 663 months |
| Engine vs AQR US momentum | corr **0.719**, 652 months |
| AQR vs Ken French (the ceiling) | corr **0.917** |
| Engine vs AQR commodity TSMOM | corr **0.680**, 331 months |
| Universe attenuation | our Sharpe **0.24** vs UMD **0.49**, same 663 months |
| Survivorship bias, measured | **+6.2%/yr** vs CRSP |
| Cross-engine agreement | **100%**, correlation 1.000, 1.1M values compared |
| Tests | **243** |
| Momentum post-publication | Sharpe **0.35 → −0.07** |
| Quote fidelity: hand-written vs AI | **31%** vs **100%** |
| Reversal | t=**9.69**, gross Sharpe 1.29, dies at 20bps, 90x turnover |
| Physical momentum (WEAKENED) | t=**4.91**, Sharpe 0.65, 41x turnover |
| Significance bar at 26 tests | t > **3.10** |
| Extraction, cold vs cached | **183s → 0.8s** |
| Schema coverage | **1,152** expressible combinations |

## Questions you will be asked

**"Why does your momentum Sharpe differ from AQR's?"**
> We trade 108 current large caps; they trade the full NYSE/AMEX universe
> including firms that no longer exist. Correlation 0.72 over 663 months says
> we're measuring the same effect; the level differs because the universe does.
> Widening it to 487 names made the correlation better and the Sharpe worse,
> because the extra breadth lands after 2000 — momentum's weak era.

**"Isn't survivorship bias fatal here?"**
> It inflates every equity result, including mine, and I measured how much.
> Against Ken French's full-CRSP factor my universe captures about **half**
> the Sharpe — 0.24 against 0.49 over the same 663 months. That's enough to
> turn a real effect insignificant, which is why every verdict reached on a
> fraction of a paper's universe prints that caveat on the card.

**"Everything fails. Isn't your tool just broken?"** — *the question to invite*
> That was my own first suspicion, so I went looking for the bug. I found
> five, and fixed them. But the reason nothing replicates isn't the engine —
> it's the data. Run my own audit arithmetic over Ken French's momentum
> factor and it **passes** both checks my momentum spec fails: t=4.63 against
> a 1.96 bar, 53% of its Sharpe retained after publication. So the engine
> agrees momentum is real when you give it a real universe. On 108 surviving
> mega-caps it can't see the effect, and it says so instead of pretending.
>
> I could have gone hunting for a construction that produced a REPLICATES for
> the demo. That is precisely the behaviour this tool exists to detect, so I
> reported the negative result instead.

**"How does a fixed engine handle arbitrary papers?"**
> Today it refuses what it can't express. The vocabulary covers 1,152
> combinations, and four of the five real arXiv papers I tried reported a
> mismatch — an R-ratio from an ARMA-GARCH model, a neural network's output,
> mass-weighted momentum. The extractor records each one instead of quietly
> approximating. The next step is letting the model generate the *signal*
> while the engine keeps positions, lag and costs — because that's the part
> that has to stay fixed for look-ahead detection to mean anything.

**"Is the backtest run by the AI's code?"**
> No. Every number comes from my engine. Claude's code produces a signal
> matrix that gets compared against mine and then discarded — it never sizes
> a position, charges a cost or computes a return. That's deliberate: if the
> AI's code ran the backtest, an AI bug would silently become my result.

**"Why not just use the Claude API?"**
> The pipeline talks to an interface, not a vendor. It runs on the Claude Code
> CLI today with no API key; swapping to the Messages API is one class.

**"What stops the AI writing code that cheats?"**
> Three layers. The spec can't represent a negative execution lag. The static
> check rejects future-reading operations before anything runs. And the audit
> re-runs with the future blinded to prove the past doesn't change.

---

## The strongest thing you can say

If you only get one extra minute, use it on this.

> I hand-wrote the reference specifications myself, because I assumed a human
> transcribing a paper would be more reliable than an AI reading one.
>
> Then I built a verifier that checks every quoted sentence actually exists in
> the paper, and ran it on both.
>
> **The AI scored 100%. I scored 31%** — nine of my thirteen quotes were
> paraphrased from memory and did not appear anywhere in the paper. One of
> them made me record the wrong transaction-cost assumption, which made three
> other parameters wrong.
>
> The tool caught its own author doing the exact thing it was built to detect.
> That check now runs automatically, and a test keeps it honest.
