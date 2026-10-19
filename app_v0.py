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
from referee.ai.verify import quote_fidelity, unverified
from referee.audit.verdict import VERDICT_MEANING, Verdict, run_audit
from referee.describe import describe_sections, describe_strategy, one_line_summary
from referee.feasibility import Level, assess
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
    stage_approve_code,
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


def preview_prices(spec: StrategySpec):
    """Prices for the feasibility panel, if we can get them without a wait.

    The reviewer sees the confirm screen before stage 4 has run, so this
    reaches for the cached panel rather than making them click through and
    come back. Returns None when the universe is one we cannot resolve, which
    is itself a finding the panel reports.
    """
    already = state().prices
    if already is not None:
        return already
    try:
        if spec.universe.tickers:
            prices, _ = load_prices(list(spec.universe.tickers))
            return prices
        if spec.universe.asset_class.value is AssetClass.US_EQUITIES:
            return get_equity_prices()[0]
        if spec.universe.asset_class.value is AssetClass.COMMODITY_FUTURES:
            return get_commodity_prices()[0]
    except Exception:
        return None
    return None


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
                # `retained` is None when there was no positive in-sample
                # Sharpe to decay from — a ratio against a losing baseline is
                # meaningless, so the check leaves it unset. Rendering a delta
                # from it would crash the tab.
                retained = c.data.get("retained")
                a, b = st.columns(2)
                a.metric("In-sample Sharpe", f"{c.data['in_sample_sharpe']:.2f}")
                b.metric(
                    f"After {c.data['publication_year']}",
                    f"{c.data['out_sample_sharpe']:.2f}",
                    delta=f"{retained - 1:+.0%}" if retained is not None else None,
                )
                if retained is None:
                    st.caption(
                        "No decay figure: the strategy had no positive "
                        "in-sample edge to decay from."
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


def render_equity_curve(result, spec: StrategySpec | None = None) -> None:
    """Growth of 1, against what the paper said you would have earned.

    The claimed line is the paper's own annual return compounded over the same
    dates. It is not a backtest of anything — it is the advertisement, drawn on
    the same axes as the measurement, so the size of the gap is visible rather
    than inferred from two numbers in a table.
    """
    curve = result.equity_curve
    fig = go.Figure()
    fig.add_scatter(
        x=curve.index, y=curve.values, mode="lines",
        name="Our replication", line=dict(width=2, color="#1f4e79"),
    )

    claimed = spec.claimed if spec else None
    if claimed and claimed.annual_return:
        rate = claimed.annual_return.value
        years = (curve.index - curve.index[0]).days / 365.25
        fig.add_scatter(
            x=curve.index, y=(1 + rate) ** years, mode="lines",
            name=f"Paper's claim ({rate:+.1%}/yr)",
            line=dict(width=2, dash="dash", color="#a4243b"),
        )

    fig.add_hline(y=1.0, line_color="grey", line_width=1)
    fig.update_layout(
        height=380, margin=dict(t=10, b=10),
        yaxis_title="growth of 1", yaxis_type="log",
        legend=dict(orientation="h", yanchor="bottom", y=1.01, x=0),
    )
    st.plotly_chart(fig, width="stretch")

    if claimed and claimed.annual_return:
        net = claimed.is_net_of_costs
        basis = (
            "net of costs" if (net and net.value)
            else "before costs" if net is not None
            else "on an unstated cost basis"
        )
        st.caption(
            f"The dashed line compounds the paper's claimed "
            f"{claimed.annual_return.value:+.2%} a year, {basis}, over our test "
            f"dates. Our line is what the same strategy actually earned on the "
            f"data we can obtain, charged at "
            f"{spec.execution.cost_bps.value:.0f}bps one-way."
        )
    else:
        st.caption(
            "The paper states no annual return we could extract, so there is "
            "no claimed line to draw against."
        )


def render_claim_comparison(report) -> None:
    """Claimed against measured, side by side, with the gap named."""
    spec, result = report.spec, report.result
    if spec is None or result is None:
        return

    stats = result.stats
    claimed = spec.claimed
    rows = []

    if claimed.annual_return:
        c = claimed.annual_return.value
        m = stats["annual_return"]
        rows.append({
            "Measure": "Annual return",
            "Paper claims": f"{c:+.2%}",
            "We measured": f"{m:+.2%}",
            "Gap": f"{m - c:+.2%}",
            "Shortfall": f"{(m / c - 1):+.0%}" if c else "—",
        })
    if claimed.sharpe:
        c = claimed.sharpe.value
        m = stats["sharpe"]
        rows.append({
            "Measure": "Sharpe ratio",
            "Paper claims": f"{c:.2f}",
            "We measured": f"{m:.2f}",
            "Gap": f"{m - c:+.2f}",
            "Shortfall": f"{(m / c - 1):+.0%}" if c else "—",
        })

    if not rows:
        st.info(
            "**No numeric claim to compare against.** The paper states neither "
            "an annual return nor a Sharpe ratio that we could extract, so the "
            "audit can judge whether the strategy works but not whether it "
            "matches what was advertised."
        )
        return

    st.markdown("#### Claimed against measured")
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

    net = claimed.is_net_of_costs
    if net is not None and not net.value and spec.execution.cost_bps.value == 0:
        st.caption(
            "Like for like: the paper's figure is gross of costs and so is "
            "ours — no transaction cost is charged in this run."
        )
    elif net is not None and net.value:
        st.caption(
            f"The paper's figure is net of its own cost assumption, and ours is "
            f"charged at {spec.execution.cost_bps.value:.0f}bps one-way to match."
        )
    else:
        st.caption(
            "Cost basis of the paper's figure is unstated, so the two numbers "
            "may not be on the same footing."
        )


LEVEL_STYLE = {
    Level.BLOCKING: ("🛑", "This will stop the run"),
    Level.SEVERE: ("⚠️", "This will shape the answer"),
    Level.NOTE: ("ℹ️", "Worth knowing"),
}


def render_not_testable(report, s) -> None:
    """Why *this* paper could not be tested — specifically, not generically.

    A refusal is only useful if it names the thing that stopped it. The
    verdict carries the blocking reason; the feasibility pass supplies
    everything else that was wrong, so the reader can tell whether it is one
    fixable problem or a paper this tool will never handle.
    """
    st.error(f"### Why this paper could not be tested\n\n{report.reason}")

    problems = assess(report.spec, s.prices) if report.spec else []
    blocking_ = [p for p in problems if p.level is Level.BLOCKING]
    others = [p for p in problems if p.level is not Level.BLOCKING]

    if blocking_:
        st.markdown("#### Everything blocking this run")
        for p in blocking_:
            st.error(f"🛑 **{p.title}** — {p.detail}")

    if others:
        with st.expander(f"Other problems found ({len(others)})"):
            for p in others:
                icon, _ = LEVEL_STYLE[p.level]
                st.markdown(f"{icon} **{p.title}** — {p.detail}")

    if report.spec:
        st.markdown("#### What we would have tested")
        with st.container(border=True):
            st.markdown(describe_strategy(report.spec))

        if report.spec.extraction_notes:
            with st.expander("Extractor notes"):
                for note in report.spec.extraction_notes:
                    st.info(note)

    st.caption(
        "This is a refusal, not a failure. The tool declines to produce a "
        "number it cannot stand behind — a confident figure for a strategy we "
        "could not actually run is the outcome this project exists to prevent."
    )


def render_report(report, s) -> None:
    """The verdict, and everything behind it."""
    render_verdict_banner(report)

    if report.verdict is Verdict.NOT_TESTABLE:
        render_not_testable(report, s)
        return

    if report.result:
        stats = report.result.stats
        cols = st.columns(4)
        cols[0].metric("Sharpe", f"{stats['sharpe']:.2f}")
        cols[1].metric("Annual return", f"{stats['annual_return']:+.1%}")
        cols[2].metric("Max drawdown", f"{stats['max_drawdown']:.1%}")
        cols[3].metric("Turnover", f"{stats['annual_turnover']:.1f}x")

        st.divider()
        render_claim_comparison(report)

        st.divider()
        st.markdown("#### Performance against the claim")
        render_equity_curve(report.result, report.spec)

    st.divider()
    st.markdown("#### The checks")
    render_checks(report)

    for note in report.notes:
        st.caption(note)


def render_feasibility(spec: StrategySpec, prices) -> list:
    """Everything that will compromise this test, before it is run."""
    problems = assess(spec, prices)
    if not problems:
        st.success(
            "No data-side problems found: we can obtain this paper's universe "
            "at full breadth, with enough history to test it."
        )
        return problems

    for level in (Level.BLOCKING, Level.SEVERE, Level.NOTE):
        here = [p for p in problems if p.level is level]
        if not here:
            continue
        icon, meaning = LEVEL_STYLE[level]
        for p in here:
            box = {Level.BLOCKING: st.error, Level.SEVERE: st.warning,
                   Level.NOTE: st.info}[level]
            box(f"{icon} **{p.title}**  \n*{meaning}.* {p.detail}")
    return problems


# -- editing the fields the paper did not state ----------------------------


def _set_by_path(spec: StrategySpec, path: str, value) -> None:
    """Write `value` into the Sourced at `path`, leaving its provenance intact.

    Confidence is deliberately *not* promoted to EXPLICIT on an edit. The paper
    still does not state this field; a person has simply made a better guess
    than the extractor did. Claiming otherwise would launder a human
    assumption into a citation, which is the exact failure this tool exists to
    catch.
    """
    parts = path.split(".")
    target = spec
    for part in parts[:-1]:
        target = getattr(target, part)
    getattr(target, parts[-1]).value = value


def _editor_for(path: str, sourced, key: str):
    """The right widget for this field's type, with its real constraints."""
    value = sourced.value

    if isinstance(value, bool):
        return st.checkbox("Corrected value", value=value, key=key)

    if hasattr(value, "value") and hasattr(type(value), "__members__"):
        options = list(type(value).__members__.values())
        return st.selectbox(
            "Corrected value", options,
            index=options.index(value),
            format_func=lambda e: e.value,
            key=key,
        )

    if path.endswith("top_fraction"):
        # (0, 0.5]: above a half the long and short legs would overlap.
        return st.number_input(
            "Corrected value", min_value=0.01, max_value=0.50,
            value=float(value), step=0.01, format="%.2f", key=key,
        )

    if path.endswith("signal_lag_days"):
        return st.number_input(
            "Corrected value", min_value=0, max_value=21,
            value=int(value), step=1, key=key,
            help="0 means trading on the same bar the signal was computed from "
                 "— not executable, and the look-ahead check will fail it.",
        )

    if isinstance(value, int):
        return st.number_input(
            "Corrected value", min_value=0, value=int(value), step=1, key=key
        )

    if isinstance(value, float):
        return st.number_input(
            "Corrected value", value=float(value), step=0.01,
            format="%.4f", key=key,
        )

    return st.text_input("Corrected value", value=str(value), key=key)


def render_spec_editor(spec: StrategySpec) -> None:
    """Let a reviewer correct any field the paper did not state outright.

    Every correction is recorded in the spec's own notes, so a changed
    parameter travels with the verdict instead of living only in the session.
    """
    queue = spec.fields_needing_review()
    if not queue:
        st.success("Every field in this specification is quoted from the paper.")
        return

    st.caption(
        "Read these before approving. Change anything the extractor got wrong "
        "— the correction is what gets backtested, and it is recorded on the "
        "verdict so the number can be traced back to it."
    )

    proposed: dict[str, object] = {}
    for path, sourced in queue:
        badge, meaning = CONFIDENCE_BADGE[sourced.confidence]
        with st.container(border=True):
            left, right = st.columns([1, 2])
            left.markdown(f"{badge} **{path}**")
            left.caption(meaning)
            with left:
                new = _editor_for(path, sourced, key=f"edit::{path}")
            if new != sourced.value:
                proposed[path] = new
                left.caption(f"↳ changed from `{sourced.value}`")

            if sourced.quote:
                right.markdown("**The sentence this came from:**")
                right.markdown(f"> {sourced.quote}")
            else:
                right.markdown(
                    "_No supporting sentence — the paper is silent and this is "
                    "our default._"
                )

    if proposed:
        st.warning(
            f"**{len(proposed)} pending correction(s).** Nothing changes until "
            f"you apply them."
        )
        if st.button("Apply corrections", type="secondary"):
            for path, value in proposed.items():
                before = _get_by_path(spec, path).value
                _set_by_path(spec, path, value)
                spec.extraction_notes.append(
                    f"Reviewer correction: {path} changed from {before!r} to "
                    f"{value!r} before the backtest was run."
                )
            state().spec_confirmed = False
            state().code_approved = False
            st.rerun()


def _get_by_path(spec: StrategySpec, path: str):
    target = spec
    for part in path.split("."):
        target = getattr(target, part)
    return target


def render_spec_review(spec: StrategySpec, editable: bool) -> StrategySpec:
    """Show every field with its evidence. Assumptions first."""
    queue = spec.fields_needing_review()
    strength = spec.evidence_strength()
    checks = state().quote_checks

    cols = st.columns(4 if checks else 3)
    cols[0].metric("Supported by the paper", f"{strength:.0%}")
    cols[1].metric("Needs review", len(queue))
    cols[2].metric(
        "Pure assumptions",
        sum(1 for _, s in queue if s.confidence is Confidence.ASSUMED),
    )
    if checks:
        cols[3].metric("Quotes verified", f"{quote_fidelity(checks):.0%}")

    missing = unverified(checks)
    if missing:
        st.error(
            f"**{len(missing)} quote(s) do not appear in the paper.** A field "
            "citing a sentence nobody wrote is a fabricated citation. Treat "
            "these as unsourced."
        )
        for m in missing:
            st.markdown(f"- `{m.path}` — \"{m.quote[:120]}\"")
    elif checks:
        st.success(
            f"All {len(checks)} quoted fields were found verbatim in the paper."
        )

    if strength < 0.25:
        st.error(
            "Almost nothing in this spec is supported by the document. "
            "This probably is not a strategy paper — see the notes below."
        )

    if spec.extraction_notes:
        with st.expander(f"Extractor notes ({len(spec.extraction_notes)})", expanded=False):
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

model = st.sidebar.selectbox(
    "Model",
    ["opus", "sonnet", "haiku"],
    index=0,
    help=(
        "Opus is the default. Extraction is the step everything downstream "
        "depends on — a misread parameter propagates into the spec, the code "
        "and the verdict — so it runs on the strongest model unless you "
        "deliberately trade that away for speed."
    ),
)
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
            "These four have independently known answers, so they show the tool "
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
            with st.spinner(f"{model} is reading the paper… (up to ~3 minutes)"):
                stage_extract(state(), get_client(model), payload)
            if state().spec_from_cache:
                st.info(
                    "**Reused a specification extracted from this PDF earlier** "
                    "— the model did not re-read the paper just now. Every "
                    "quote in it was re-checked against the document a moment "
                    "ago, so the evidence below is current even though the "
                    "reading is not."
                )
            else:
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
        prices = preview_prices(s.spec)

        if s.spec_from_cache:
            st.info(
                "This specification was reused from an earlier extraction of "
                "the same PDF, not read just now. Its quotes were re-verified "
                "against the document when it was loaded."
            )

        st.subheader("The strategy in full")
        st.caption(
            "Written out from the specification itself, so it cannot drift "
            "from what actually gets backtested. Read it against the paper."
        )
        with st.container(border=True):
            st.markdown(describe_strategy(s.spec))

        st.divider()
        st.subheader("What will compromise this test")
        st.caption(
            "Not only whether the paper was read correctly — also whether we "
            "can honestly test it with the data available."
        )
        problems = render_feasibility(s.spec, prices)

        st.divider()
        st.subheader("How much of this came from the paper")
        render_spec_review(s.spec, editable=True)

        st.divider()
        st.subheader("Correct anything the extractor got wrong")
        render_spec_editor(s.spec)

        st.divider()
        blockers = [p for p in problems if p.level is Level.BLOCKING]
        if blockers:
            st.error(
                f"**{len(blockers)} blocking problem(s).** You may still "
                f"confirm, but the audit will refuse to produce a number and "
                f"will tell you which of these stopped it."
            )
        if s.spec_confirmed:
            st.success("Confirmed — code generation unlocked in tab 3.")
        label = (
            "Re-confirm this specification" if s.spec_confirmed
            else "I have reviewed this specification"
        )
        if st.button(label, type="primary"):
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
        if st.button(
            "Regenerate code" if s.code else "Generate code", type="primary"
        ):
            with st.spinner(f"{model} is writing the signal function…"):
                stage_generate(s, get_client(model))
            st.rerun()

        if s.code:
            problems = check_code(s.code)

            st.markdown("#### What this code is supposed to implement")
            st.caption(
                "The specification you approved, restated. Check the code "
                "against this, not against your memory of the paper."
            )
            spec_side, code_side = st.columns([1, 1])

            with spec_side:
                for section in describe_sections(s.spec):
                    if section.heading.startswith(("2.", "3.", "4.", "5.")):
                        with st.container(border=True):
                            st.markdown(f"**{section.heading}**")
                            st.markdown(section.body)

            with code_side:
                st.code(s.code, language="python")

            st.divider()
            st.markdown("#### Automated checks")
            if problems:
                st.error(
                    "**Static check failed.** This code will not be allowed to "
                    "run:\n" + "\n".join(f"- {p}" for p in problems)
                )
            else:
                st.success(
                    "**Static check passed** — no look-ahead patterns, no "
                    "imports outside pandas and numpy, no file or network "
                    "access."
                )
                st.caption(
                    "This proves the code is *safe* and *causal*. It does not "
                    "prove it implements the right strategy — only you can say "
                    "that, which is why the next step exists."
                )

            st.divider()
            st.markdown("#### Your approval")
            if s.code_approved:
                st.success(
                    "Approved. This code is what runs for the cross-engine "
                    "check in the audit."
                )
            else:
                st.warning(
                    "**Not yet approved.** The specification gate catches a "
                    "misread paper. This gate catches a misread specification: "
                    "code that is safe, runs clean, and computes the wrong "
                    "thing. Nothing is executed against real prices until you "
                    "have read it."
                )

            can_approve = not problems
            if st.button(
                "This code implements the specification — approve and run",
                type="primary",
                disabled=not can_approve or s.code_approved,
            ):
                from referee.pipeline import stage_load_data

                stage_approve_code(s)
                with st.spinner("Loading prices and running in the sandbox…"):
                    if s.prices is None:
                        stage_load_data(s)
                    stage_run_sandboxed(s)
                st.rerun()

            if not can_approve:
                st.caption(
                    "Approval is disabled while the static check is failing. "
                    "Regenerate the code."
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
        if s.prices is None and s.report is None:
            from referee.pipeline import stage_audit, stage_load_data

            if st.button("Load data and audit", type="primary"):
                with st.spinner("Loading prices…"):
                    stage_load_data(s)
                    # If the universe could not be resolved, prices stay None.
                    # Run the audit anyway: it is the thing that knows how to
                    # refuse, and a refusal with a reason is the answer here.
                    if s.prices is None:
                        stage_audit(s)
                st.rerun()
        elif s.prices is not None:
            if mode == "Replication":
                st.caption(
                    "Every parameter locked to the paper's own values. One question: "
                    "does the claim hold?"
                )

                # A verdict is a statement about a strategy, and the only
                # evidence that we implemented the right strategy is a second
                # implementation someone has read. Reaching the verdict
                # without that step would leave the cross-engine check
                # permanently N/A and the claim resting on one unreviewed
                # reading of the spec.
                skip_cross_engine = False
                if not s.code:
                    st.warning(
                        "**No code generated yet.** Generate it in tab 3 and "
                        "read it before the audit runs. The verdict rests on "
                        "the strategy being implemented correctly, and the "
                        "cross-engine check is what tests that."
                    )
                elif not s.code_approved:
                    st.warning(
                        "**The generated code has not been approved.** Read it "
                        "in tab 3 and approve it there. Until then the audit "
                        "would be judging a strategy nobody has confirmed we "
                        "implemented correctly."
                    )

                if not s.code_approved:
                    # The gate is the right default, but it makes every verdict
                    # depend on a model call. When the model is slow or
                    # unreachable, the choice is between no answer at all and
                    # an answer with one of six checks missing — and the second
                    # is more useful, provided the omission is stated rather
                    # than hidden.
                    skip_cross_engine = st.checkbox(
                        "Run without the cross-engine check",
                        help=(
                            "Five checks instead of six. The engine still "
                            "tests look-ahead, costs, out-of-sample behaviour, "
                            "parameter sensitivity and significance — but "
                            "nothing verifies that our implementation of the "
                            "spec agrees with a second, independent one. The "
                            "verdict will say so."
                        ),
                    )
                    if skip_cross_engine:
                        st.info(
                            "The cross-engine check will be skipped and marked "
                            "as such on the verdict."
                        )

                if st.button(
                    "Run the audit",
                    type="primary",
                    disabled=not (s.code_approved or skip_cross_engine),
                ):
                    from referee.pipeline import stage_audit

                    with st.spinner("Running the checks…"):
                        stage_audit(s)
                        if skip_cross_engine and s.report:
                            s.report.notes.append(
                                "Cross-engine agreement was skipped at the "
                                "operator's request: no second implementation "
                                "was generated or approved, so nothing checked "
                                "that our reading of the specification is the "
                                "only reasonable one. Five checks ran, not six."
                            )
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
                render_report(s.report, s)

        if s.prices is None and s.report is not None:
            render_report(s.report, s)


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
