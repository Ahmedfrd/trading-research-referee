"""The Replication Referee — Streamlit interface.

Five tabs mirroring the pipeline, plus the system prompts on screen. The
prompts are a tab rather than a hidden implementation detail because how the
AI was instructed is part of what is being presented.
"""

from __future__ import annotations

import logging
import warnings
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.INFO)

from referee.ai.client import ClaudeCLIClient, LLMError, load_prompt
from referee.ai.generate import check_code
from referee.audit.verdict import VERDICT_MEANING, Verdict, run_audit
from referee.data.loaders import coverage_table, load_prices
from referee.data.universes import (
    MOP_COMMODITIES,
    commodity_tickers,
    unobtainable,
    us_large_cap_tickers,
)
from referee.engine.backtest import run_backtest
from referee.papers import ALL_PAPERS
from referee.pipeline import (
    PipelineState,
    stage_confirm,
    stage_extract,
    stage_generate,
    stage_run_sandboxed,
)
from referee.spec import AssetClass, Confidence, StrategySpec

st.set_page_config(page_title="The Replication Referee", page_icon="⚖️", layout="wide")

VERDICT_STYLE = {
    Verdict.REPLICATES: ("#0b6e4f", "✓"),
    Verdict.WEAKENED: ("#b8860b", "~"),
    Verdict.FAILS: ("#a4243b", "✕"),
    Verdict.NOT_TESTABLE: ("#4a5568", "—"),
}

CONFIDENCE_BADGE = {
    Confidence.EXPLICIT: ("🟢", "stated in the paper"),
    Confidence.INFERRED: ("🟡", "inferred from the paper"),
    Confidence.ASSUMED: ("🔴", "NOT in the paper — our assumption"),
}


# --------------------------------------------------------------------------
# Cached data
# --------------------------------------------------------------------------


@st.cache_data(show_spinner="Loading price history…")
def get_commodity_prices():
    prices, coverage = load_prices(commodity_tickers())
    return prices, coverage_table(coverage)


@st.cache_data(show_spinner="Loading US equity history…")
def get_equity_prices():
    prices, coverage = load_prices(us_large_cap_tickers())
    return prices, coverage_table(coverage)


@st.cache_resource
def get_client(model: str):
    return ClaudeCLIClient(model=model)


def state() -> PipelineState:
    if "pipeline" not in st.session_state:
        st.session_state.pipeline = PipelineState()
    return st.session_state.pipeline


# --------------------------------------------------------------------------
# Shared rendering
# --------------------------------------------------------------------------


def render_verdict_banner(report) -> None:
    colour, mark = VERDICT_STYLE[report.verdict]
    st.markdown(
        f"""<div style="background:{colour};color:#fff;padding:20px 26px;
        border-radius:10px;margin-bottom:14px;">
        <div style="font-size:34px;font-weight:700;letter-spacing:1px;">
        {mark} {report.verdict.value}</div>
        <div style="font-size:16px;opacity:.93;margin-top:4px;">
        {VERDICT_MEANING[report.verdict]}</div>
        <div style="font-size:15px;opacity:.85;margin-top:6px;">{report.reason}</div>
        </div>""",
        unsafe_allow_html=True,
    )


def render_checks(report) -> None:
    for c in report.checks:
        icon = {"PASS": "✅", "FAIL": "❌", "N/A": "⬜"}[c.status]
        with st.expander(f"{icon}  **{c.name}** — {c.headline}", expanded=not c.passed):
            st.write(c.detail)

            if c.name == "Transaction costs" and c.data.get("curve"):
                curve = c.data["curve"]
                fig = go.Figure()
                fig.add_scatter(
                    x=list(curve), y=list(curve.values()),
                    mode="lines+markers", name="Sharpe", line=dict(width=3),
                )
                fig.add_hline(y=0, line_dash="dash", line_color="grey")
                fig.add_vline(
                    x=c.data["realistic_bps"], line_dash="dot", line_color="#a4243b",
                    annotation_text="realistic cost",
                )
                fig.update_layout(
                    height=320, margin=dict(t=10, b=10),
                    xaxis_title="one-way cost (basis points)",
                    yaxis_title="Sharpe ratio",
                )
                st.plotly_chart(fig, width="stretch")

            elif c.name == "Parameter sensitivity" and c.data.get("grid"):
                grid = c.data["grid"]
                colours = [
                    "#a4243b" if k == c.data["published_lookback"] else "#4a6fa5"
                    for k in grid
                ]
                fig = go.Figure(
                    go.Bar(x=[str(k) for k in grid], y=list(grid.values()),
                           marker_color=colours)
                )
                fig.add_hline(y=0, line_color="grey")
                fig.update_layout(
                    height=320, margin=dict(t=10, b=10),
                    xaxis_title="lookback (days) — red is the published value",
                    yaxis_title="Sharpe ratio",
                )
                st.plotly_chart(fig, width="stretch")

            elif c.name == "Out-of-sample" and c.applicable:
                a, b = st.columns(2)
                a.metric("In-sample Sharpe", f"{c.data['in_sample_sharpe']:.2f}")
                b.metric(
                    f"After {c.data['publication_year']}",
                    f"{c.data['out_sample_sharpe']:.2f}",
                    delta=f"{c.data['retained'] - 1:+.0%}",
                )

            elif c.name == "Multiple testing":
                n = c.data["n_tests"]
                if n == 1:
                    a, b = st.columns(2)
                    a.metric("t-statistic", f"{c.data['t_statistic']:.2f}")
                    b.metric("Bar to clear", f"{c.data['naive_bar']:.2f}")
                    st.caption(
                        "Test a second variant and this bar rises. The tool gets "
                        "harder to please the more you try."
                    )
                else:
                    a, b, d = st.columns(3)
                    a.metric("t-statistic", f"{c.data['t_statistic']:.2f}")
                    b.metric("Bar after 1 test", f"{c.data['naive_bar']:.2f}")
                    d.metric(
                        f"Bar after {n} tests",
                        f"{c.data['adjusted_bar']:.2f}",
                        delta=f"{c.data['adjusted_bar'] - c.data['naive_bar']:+.2f}",
                        delta_color="inverse",
                    )


def render_equity_curve(result) -> None:
    curve = result.equity_curve
    fig = go.Figure()
    fig.add_scatter(x=curve.index, y=curve.values, mode="lines",
                    name="Strategy", line=dict(width=2))
    fig.update_layout(
        height=340, margin=dict(t=10, b=10),
        yaxis_title="growth of 1", yaxis_type="log",
    )
    st.plotly_chart(fig, width="stretch")


def render_spec_review(spec: StrategySpec, editable: bool) -> StrategySpec:
    """Show every field with its evidence. Assumptions first."""
    queue = spec.fields_needing_review()
    strength = spec.evidence_strength()

    a, b, c = st.columns(3)
    a.metric("Supported by the paper", f"{strength:.0%}")
    b.metric("Needs review", len(queue))
    c.metric(
        "Pure assumptions",
        sum(1 for _, s in queue if s.confidence is Confidence.ASSUMED),
    )

    if strength < 0.25:
        st.error(
            "Almost nothing in this spec is supported by the document. "
            "This probably is not a strategy paper — see the notes below."
        )

    st.markdown("#### Fields the paper did not state outright")
    st.caption("A reviewer should read these first. Everything else was quoted directly.")

    for path, sourced in queue:
        badge, meaning = CONFIDENCE_BADGE[sourced.confidence]
        with st.container(border=True):
            left, right = st.columns([1, 2])
            left.markdown(f"{badge} **{path}**")
            left.code(str(sourced.value), language=None)
            right.caption(meaning)
            if sourced.quote:
                right.markdown(f"> {sourced.quote}")
            else:
                right.markdown("_No supporting sentence — this is our default._")

    if spec.extraction_notes:
        st.markdown("#### Extractor notes")
        for note in spec.extraction_notes:
            st.info(note)

    with st.expander("Full specification (JSON)"):
        st.json(spec.model_dump(mode="json"))

    return spec


# --------------------------------------------------------------------------
# Sidebar
# --------------------------------------------------------------------------

st.sidebar.title("⚖️ Replication Referee")
st.sidebar.caption("Does the claimed edge survive contact with reality?")

model = st.sidebar.selectbox("Model", ["sonnet", "opus", "haiku"], index=0)
mode = st.sidebar.radio(
    "Mode",
    ["Replication", "Robustness"],
    help=(
        "Replication locks every parameter to the paper's own values and answers "
        "one question: does the claim hold?\n\n"
        "Robustness lets you vary settings — and never returns a single number, "
        "only the distribution across the whole sweep. That is deliberate: a tool "
        "that returns one number per setting is a machine for overfitting."
    ),
)

st.sidebar.divider()
st.sidebar.metric("Variants tested this session", state().variants_tested)
st.sidebar.caption(
    "Every variant raises the statistical bar. The tool gets harder to please "
    "the more you fiddle with it."
)
if st.sidebar.button("Reset session"):
    st.session_state.clear()
    st.rerun()


# --------------------------------------------------------------------------
# Tabs
# --------------------------------------------------------------------------

tabs = st.tabs(
    ["1 · Paper", "2 · Confirm", "3 · Code", "4 · Verdict", "Data", "Prompts"]
)

# -- 1. Paper --------------------------------------------------------------

with tabs[0]:
    st.header("Upload a paper")
    st.caption(
        "The AI reads it into a structured specification. Nothing is backtested "
        "until you have reviewed that specification in the next tab."
    )

    source = st.radio(
        "Source", ["Reference paper", "Upload PDF", "Paste text"], horizontal=True
    )

    payload = None
    if source == "Reference paper":
        st.info(
            "These three have independently known answers, so they show the tool "
            "works rather than just that it runs."
        )
        choice = st.selectbox(
            "Paper",
            list(ALL_PAPERS),
            format_func=lambda k: {
                "momentum": "Cross-Sectional Momentum (Jegadeesh & Titman 1993)",
                "tsmom": "Time Series Momentum (Moskowitz, Ooi & Pedersen 2012)",
                "reversal": "Short-Term Reversal (de Groot, Huij & Zhou)",
                "technical": "Technical Trading Rules (Brock, Lakonishok & LeBaron 1992)",
            }[k],
        )
        if st.button("Load reference specification", type="primary"):
            s = state()
            s.spec = ALL_PAPERS[choice]()
            s.spec_confirmed = False
            s.source_name = f"reference: {choice}"
            st.success("Loaded. Review it in tab 2.")

    elif source == "Upload PDF":
        upload = st.file_uploader("Research paper", type="pdf")
        if upload:
            payload = Path(st.session_state.get("_tmpdir", "/tmp")) / upload.name
            payload.write_bytes(upload.getbuffer())
    else:
        text = st.text_area("Paper text", height=260)
        payload = text if text.strip() else None

    if payload is not None and st.button("Extract specification", type="primary"):
        try:
            with st.spinner("Claude is reading the paper…"):
                stage_extract(state(), get_client(model), payload)
            st.success("Extracted. Review it in tab 2 before anything is run.")
        except LLMError as exc:
            st.error(str(exc))

    if state().spec:
        st.divider()
        st.subheader(state().spec.paper.title)
        st.caption(
            f"{', '.join(state().spec.paper.authors)} ({state().spec.paper.year})"
        )
        st.write(state().spec.signal.description)

# -- 2. Confirm ------------------------------------------------------------

with tabs[1]:
    st.header("Confirm the specification")
    st.markdown(
        "**This step is the point, not a compromise.** AI misreads papers. "
        "Rather than hoping it will not, the tool shows you every field it was "
        "not certain about, with the sentence it came from, and refuses to "
        "generate code until you have looked."
    )

    s = state()
    if s.spec is None:
        st.info("Load or extract a paper first.")
    else:
        render_spec_review(s.spec, editable=True)
        st.divider()
        if s.spec_confirmed:
            st.success("Confirmed — code generation unlocked.")
        if st.button("I have reviewed this specification", type="primary"):
            stage_confirm(s)
            st.rerun()

# -- 3. Code ---------------------------------------------------------------

with tabs[2]:
    st.header("Generated code")
    st.caption(
        "Generated from the confirmed specification — never from the raw PDF. "
        "Checked statically for look-ahead bias and unsafe operations before it "
        "is allowed to run, then executed in an isolated subprocess."
    )

    s = state()
    if not s.spec_confirmed:
        st.warning("Confirm the specification in tab 2 first.")
    else:
        if st.button("Generate and run", type="primary"):
            with st.spinner("Writing the signal function…"):
                stage_generate(s, get_client(model))
            if s.code:
                from referee.pipeline import stage_load_data

                with st.spinner("Loading prices and running in the sandbox…"):
                    stage_load_data(s)
                    stage_run_sandboxed(s)
            st.rerun()

        if s.code:
            st.code(s.code, language="python")

            problems = check_code(s.code)
            if problems:
                st.error("Static check failed:\n" + "\n".join(f"- {p}" for p in problems))
            else:
                st.success(
                    "Static check passed — no look-ahead patterns, no imports "
                    "outside pandas and numpy, no file or network access."
                )

            if s.sandbox:
                if s.sandbox.ok:
                    st.success(
                        f"Executed in the sandbox in {s.sandbox.duration_s:.1f}s; "
                        f"returned a valid signal of shape {s.sandbox.signal.shape}."
                    )
                else:
                    st.error(f"Sandbox rejected the run: {s.sandbox.error}")

        for err in s.errors:
            st.warning(err)

# -- 4. Verdict ------------------------------------------------------------

with tabs[3]:
    st.header("Verdict")

    s = state()
    if s.spec is None:
        st.info("Load a paper first.")
    else:
        if s.prices is None:
            from referee.pipeline import stage_load_data

            if st.button("Load data and audit", type="primary"):
                with st.spinner("Loading prices…"):
                    stage_load_data(s)
                st.rerun()
        else:
            if mode == "Replication":
                st.caption(
                    "Every parameter locked to the paper's own values. One question: "
                    "does the claim hold?"
                )
                if st.button("Run the audit", type="primary"):
                    from referee.pipeline import stage_audit

                    with st.spinner("Running six checks…"):
                        stage_audit(s)
                    st.rerun()
            else:
                st.caption(
                    "Robustness mode never returns a single result. It sweeps and "
                    "reports the whole distribution, so the question changes from "
                    "*which setting is best?* to *does this work across settings?*"
                )
                lo, hi = st.slider(
                    "Lookback range (days)", 20, 500,
                    (
                        max(20, int(s.spec.signal.lookback_days.value * 0.5)),
                        int(s.spec.signal.lookback_days.value * 1.5),
                    ),
                )
                cost = st.slider("One-way cost (bps)", 0, 100, 5)

                if st.button("Sweep", type="primary"):
                    grid = list(range(lo, hi + 1, max(1, (hi - lo) // 12)))
                    rows = []
                    bar = st.progress(0.0)
                    for i, lb in enumerate(grid):
                        r = run_backtest(
                            s.prices, s.spec, lookback_override=lb, cost_bps=cost
                        )
                        rows.append({"lookback": lb, **r.stats})
                        s.variants_tested += 1
                        bar.progress((i + 1) / len(grid))
                    bar.empty()
                    st.session_state.sweep = pd.DataFrame(rows)

                if "sweep" in st.session_state:
                    sweep = st.session_state.sweep
                    a, b, c = st.columns(3)
                    a.metric("Median Sharpe", f"{sweep.sharpe.median():.2f}")
                    b.metric("Worst", f"{sweep.sharpe.min():.2f}")
                    c.metric("Profitable settings", f"{(sweep.sharpe > 0).mean():.0%}")

                    fig = go.Figure(go.Bar(x=sweep.lookback, y=sweep.sharpe))
                    fig.add_hline(y=0, line_color="grey")
                    fig.update_layout(
                        height=340, xaxis_title="lookback (days)",
                        yaxis_title="Sharpe ratio", margin=dict(t=10, b=10),
                    )
                    st.plotly_chart(fig, width="stretch")
                    st.dataframe(sweep, width="stretch")

            if s.report:
                st.divider()
                render_verdict_banner(s.report)

                if s.report.result:
                    st_ = s.report.result.stats
                    cols = st.columns(4)
                    cols[0].metric("Sharpe", f"{st_['sharpe']:.2f}")
                    cols[1].metric("Annual return", f"{st_['annual_return']:+.1%}")
                    cols[2].metric("Max drawdown", f"{st_['max_drawdown']:.1%}")
                    cols[3].metric("Turnover", f"{st_['annual_turnover']:.1f}x")
                    render_equity_curve(s.report.result)

                render_checks(s.report)

                for note in s.report.notes:
                    st.caption(note)

# -- 5. Data ---------------------------------------------------------------

with tabs[4]:
    st.header("Data coverage")
    st.caption(
        "What the paper used, what we could obtain, and what we could not. "
        "A tool that knows its own limits is more credible than one that "
        "silently produces a number."
    )

    s = state()
    spec_class = s.spec.universe.asset_class.value if s.spec else None

    universe = st.radio(
        "Universe",
        ["Commodity futures", "US large caps"],
        horizontal=True,
        index=1 if spec_class is AssetClass.US_EQUITIES else 0,
        help="Defaults to the universe the loaded paper actually trades.",
    )

    if universe == "Commodity futures":
        prices, table = get_commodity_prices()
        a, b, c = st.columns(3)
        a.metric("Contracts in the paper", len(MOP_COMMODITIES))
        b.metric("Obtained", int(table.usable.sum()))
        c.metric("No free source", len(unobtainable()))
        st.caption(
            "The three unobtainable contracts (Gasoil, Nickel, Zinc) are LME and "
            "ICE London contracts with no free daily feed. They are kept in the "
            "list rather than deleted, so the gap is reported instead of implied "
            "away."
        )
    else:
        prices, table = get_equity_prices()
        a, b, c = st.columns(3)
        a.metric("Names attempted", len(table))
        b.metric("Usable", int(table.usable.sum()))
        c.metric("History from", str(prices.index[0].date()) if len(prices) else "—")
        st.caption(
            "The paper trades every NYSE and AMEX stock. This is a much narrower "
            "set of current large caps — see the survivorship note below."
        )

    st.dataframe(table, width="stretch", hide_index=True)

    st.markdown("#### Stated limitations")
    st.warning(
        "**Survivorship bias.** Free data gives today's index members, not "
        "historical membership, so backtests silently include only survivors. "
        "Companies that failed are absent, which flatters every equity result. "
        "There is no clean free fix.\n\n"
        "**Futures roll gaps.** Yahoo's continuous contracts stitch months "
        "together without back-adjustment, adding noise at each roll. This "
        "depresses measured Sharpe against properly roll-adjusted series.\n\n"
        "**Partial sandbox.** Generated code runs in an isolated subprocess with "
        "an import allowlist and CPU limits, not a container. Proportionate to "
        "the threat of wrong AI code; not proof against a hostile attacker."
    )

# -- 6. Prompts ------------------------------------------------------------

with tabs[5]:
    st.header("System prompts")
    st.caption(
        "The exact instructions given to the model, versioned in the repository "
        "and passed explicitly on every call. How the AI was instructed is part "
        "of the product, not a hidden detail."
    )
    for name, label in [
        ("extract_spec", "Stage 1 — paper to specification"),
        ("generate_code", "Stage 3 — specification to code"),
    ]:
        st.subheader(label)
        st.code(load_prompt(name), language="markdown")
