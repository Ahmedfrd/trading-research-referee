# Demo run sheet

Measured end to end: **3.2 seconds** of tool time, zero errors. Everything
below is timing for *you talking*, not for the software waiting.

Start the app before recording, click through once to warm the caches, then
hit Reset session in the sidebar.

```bash
.venv/bin/streamlit run app.py
```

---

## The 3-minute demo

### 0:00 — The problem (~25s)

> Hou, Xue and Zhang tested 447 published market anomalies. **64% were
> statistically insignificant.** At the stricter t > 3 bar, **85% failed.**
> McLean and Pontiff tracked 97 return predictors: returns were **26% lower**
> on fresh data, **58% lower after publication**.
>
> Checking one paper by hand takes an analyst one to two weeks. This does it
> in about three seconds.

### 0:25 — Tab 1, load the paper (~15s)

Select **Cross-Sectional Momentum (Jegadeesh & Titman 1993)** → *Load
reference specification*.

> This is the most-replicated anomaly in finance. Buy last year's winners,
> short last year's losers. If the tool can't handle this one, nothing else
> it says matters.

### 0:40 — Tab 2, the human gate (~35s) — **the most important 35 seconds**

> The AI read the paper into a structured specification. It does **not** get
> to go straight to code.
>
> Every field carries the exact sentence it came from. Green means the paper
> stated it. Yellow means inferred. **Red means the paper never said this and
> the AI is guessing** — here, the execution lag. The paper is silent on it,
> and it's the single field that decides whether the backtest is honest.
>
> Most student projects hide that their AI is fallible. I built for it.

Click *I have reviewed this specification*.

### 1:15 — Tab 3, generated code (~25s)

*Generate and run.*

> Generated from the reviewed specification — never from the raw PDF. Then
> checked before it runs: no reading future rows, no imports beyond pandas
> and numpy, no file or network access. Then executed in an isolated
> subprocess with a CPU limit and a timeout.

### 1:40 — Tab 4, the verdict (~50s)

*Run the audit.*

> The most-replicated anomaly in finance. It passes look-ahead testing. It
> survives realistic costs. It works across a broad range of parameters, not
> one lucky number.
>
> And it **stopped working after it was published**. Sharpe **0.55** on the
> years Jegadeesh and Titman studied. **−0.02** on everything since. That's
> McLean and Pontiff's finding, measured live, on the canonical paper.

Open the **Cross-engine agreement** check.

> Two independent implementations of the same specification — mine written by
> hand, Claude's generated from the spec. They agree 100%. If they disagreed,
> at least one would be wrong, and you should not trust the number.

### 2:30 — The cost slider flip (~30s) — **the money shot**

Reset session → load **Short-Term Reversal** → confirm → audit.

> Gross Sharpe **1.35**. Seventeen percent a year. t-statistic **10.2** —
> this effect is beyond question real.
>
> And it **fails**. It turns over ninety times a year, and the edge is gone
> by twenty basis points. Real, and untradeable.

Open the **Transaction costs** check to show the curve crossing zero.

---

## If you have another 30 seconds

**The multiple-testing counter.** Switch to **Robustness** mode, sweep, and
watch the sidebar counter climb.

> Robustness mode never returns one number — only the distribution. And every
> variant you try raises the statistical bar. Test one strategy, you need
> t=1.96. Test twenty-six — which is exactly how many rules Brock, Lakonishok
> and LeBaron tested in 1992 — you need **t=3.10**.
>
> The tool gets harder to please the more you fiddle with it. That's
> deliberate: a tool that lets you spin dials until something looks good is a
> machine for manufacturing the exact problem it exists to detect.

**The refusal.** Upload `data/papers/negative_control_school_autonomy.pdf`.

> That's an education-economics paper about school autonomy. No trading
> strategy anywhere in it. The tool doesn't invent one — it marks every field
> as an assumption and refuses to produce a backtest that would look
> meaningful and mean nothing.

---

## Numbers to have ready

| Claim | Number |
|---|---|
| Engine vs Ken French UMD | corr **0.738**, 652 months |
| Engine vs AQR US momentum | corr **0.729**, 652 months |
| AQR vs Ken French (the ceiling) | corr **0.917** |
| Survivorship bias, measured | **+6.2%/yr** vs CRSP |
| Engine vs AQR commodity TSMOM | corr **0.680**, 331 months |
| Cross-engine agreement | **100%**, correlation 1.000 |
| Tests | **84** |
| Momentum post-publication | Sharpe **0.55 → −0.02** |
| Quote fidelity: hand-written vs AI | **31%** vs **100%** |
| Reversal | t=**10.20**, gross Sharpe 1.35, dies at 20bps, 90x turnover |
| Significance bar at 26 tests | t > **3.10** |

## Questions you will be asked

**"Why does your momentum Sharpe differ from AQR's?"**
> We trade 108 current large caps; they trade the full NYSE/AMEX universe
> including firms that no longer exist. Correlation 0.71 over 652 months says
> we're measuring the same effect; the level differs because the universe does.

**"Isn't survivorship bias fatal here?"**
> It inflates every equity result, including mine. I state it rather than
> hide it. It cuts *against* my headline finding, though — momentum decayed
> 80% even on a universe biased in its favour.

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
