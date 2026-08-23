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

> The most-replicated anomaly in finance. It passes look-ahead testing and it
> survives realistic costs.
>
> And it **stopped working after it was published**. Sharpe **0.35** on the
> years Jegadeesh and Titman studied. **−0.07** on everything since. That's
> McLean and Pontiff's finding, measured live, on the canonical paper.

Then point at the coverage note at the bottom of the card, before anyone else
does:

> It says FAILS, and I'll tell you why that verdict is only half about the
> paper. We tested **108 stocks; Jegadeesh and Titman used the whole NYSE and
> AMEX**. Momentum lives in the small names and the ones that went bust —
> exactly what a list of today's survivors leaves out. Run my own audit
> arithmetic over Ken French's proper factor and momentum **passes**. The tool
> prints that caveat itself rather than letting me quietly take credit for a
> harsh-looking result.

Open the **Cross-engine agreement** check.

> Two independent implementations of the same specification — mine written by
> hand, Claude's generated from the spec. They agree 100%. If they disagreed,
> at least one would be wrong, and you should not trust the number.

### 2:30 — The cost slider flip (~30s) — **the money shot**

Reset session → load **Short-Term Reversal** → confirm → audit.

> Gross Sharpe **1.29**. Sixteen percent a year. t-statistic **9.7** —
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
| Engine vs Ken French UMD | corr **0.718**, 663 months |
| Engine vs AQR US momentum | corr **0.719**, 652 months |
| AQR vs Ken French (the ceiling) | corr **0.917** |
| Survivorship bias, measured | **+6.2%/yr** vs CRSP |
| Universe attenuation | our Sharpe **0.24** vs UMD **0.49**, same 663 months |
| Engine vs AQR commodity TSMOM | corr **0.680**, 331 months |
| Cross-engine agreement | **100%**, correlation 1.000, 1.1M values compared |
| Tests | **199** |
| Momentum post-publication | Sharpe **0.35 → −0.07** |
| Quote fidelity: hand-written vs AI | **31%** vs **100%** |
| Reversal | t=**9.69**, gross Sharpe 1.29, dies at 20bps, 90x turnover |
| Significance bar at 26 tests | t > **3.10** |

## Questions you will be asked

**"Why does your momentum Sharpe differ from AQR's?"**
> We trade 108 current large caps; they trade the full NYSE/AMEX universe
> including firms that no longer exist. Correlation 0.71 over 652 months says
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
