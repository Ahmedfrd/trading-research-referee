"""The pipeline, as five explicit stages.

    PDF -> EXTRACT -> [HUMAN CONFIRM] -> GENERATE -> RUN (sandboxed) -> AUDIT

Stages are separate functions rather than one call because stage 2 is a human
pause. The state object carries everything forward so the UI can render each
stage as it completes and let the reviewer intervene before code exists.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from referee.ai.client import LLMClient, LLMError
from referee.ai.extract import extract_spec, read_pdf
from referee.ai.generate import UnsafeCode, generate_code
from referee.ai.verify import QuoteCheck, quote_fidelity, verify_quotes
from referee.audit.verdict import AuditReport, Verdict, run_audit
from referee.data.loaders import Coverage, load_prices
from referee.data.universes import (
    commodity_tickers,
    unobtainable,
    us_large_cap_tickers,
)
from referee.engine.sandbox import SandboxResult, run_generated_signal
from referee.spec import AssetClass, StrategySpec

log = logging.getLogger(__name__)


@dataclass
class PipelineState:
    """Everything produced so far. Each stage fills in its own fields."""

    paper_text: str = ""
    source_name: str = ""

    spec: StrategySpec | None = None
    spec_confirmed: bool = False

    quote_checks: list[QuoteCheck] = field(default_factory=list)
    """Whether each claimed quote actually appears in the paper."""

    code: str = ""
    sandbox: SandboxResult | None = None

    prices: pd.DataFrame | None = None
    coverage: list[Coverage] = field(default_factory=list)

    report: AuditReport | None = None
    errors: list[str] = field(default_factory=list)

    # Raised by the multiple-testing check: every variant tried counts.
    variants_tested: int = 0


# --------------------------------------------------------------------------
# Stage 1 — extract
# --------------------------------------------------------------------------


def stage_extract(
    state: PipelineState, client: LLMClient, source: str | Path
) -> PipelineState:
    """Read the paper into a spec. Output is a draft for a human, not a result."""
    path = Path(source)
    if path.exists() and path.suffix.lower() == ".pdf":
        state.paper_text = read_pdf(path)
        state.source_name = path.name
    else:
        state.paper_text = str(source)
        state.source_name = "pasted text"

    state.spec, _ = extract_spec(client, state.paper_text)
    state.spec_confirmed = False

    # A quote that is not in the paper is a fabricated citation, whether an AI
    # or a person wrote it. Check before a human is asked to trust the spec.
    state.quote_checks = verify_quotes(state.spec, state.paper_text)
    fidelity = quote_fidelity(state.quote_checks)
    if fidelity < 1.0:
        state.errors.append(
            f"{sum(not c.found for c in state.quote_checks)} of "
            f"{len(state.quote_checks)} quotes do not appear in the paper "
            f"({fidelity:.0%} verified). Treat those fields as unsourced."
        )
    return state


# --------------------------------------------------------------------------
# Stage 2 — human confirmation
#
# Not a compromise. AI misreads papers; this is the guard rail built for that
# rather than a hope that it will not happen. The UI shows every assumed and
# inferred field with the sentence it came from, and nothing proceeds until a
# person has looked.
# --------------------------------------------------------------------------


def stage_confirm(state: PipelineState, spec: StrategySpec | None = None) -> PipelineState:
    """Record that a human has reviewed (and possibly corrected) the spec."""
    if spec is not None:
        state.spec = spec
    if state.spec is None:
        raise ValueError("nothing to confirm — run extraction first")
    state.spec_confirmed = True
    return state


# --------------------------------------------------------------------------
# Stage 3 — generate
# --------------------------------------------------------------------------


def stage_generate(state: PipelineState, client: LLMClient) -> PipelineState:
    """Generate a signal function from the confirmed spec."""
    if not state.spec_confirmed:
        raise ValueError(
            "the spec must be confirmed by a human before code is generated"
        )
    try:
        state.code, _ = generate_code(client, state.spec)
    except (UnsafeCode, LLMError) as exc:
        state.errors.append(f"code generation failed: {exc}")
    return state


# --------------------------------------------------------------------------
# Stage 4 — load data and run
# --------------------------------------------------------------------------

UNIVERSE_TICKERS = {
    AssetClass.COMMODITY_FUTURES: commodity_tickers,
    AssetClass.US_EQUITIES: us_large_cap_tickers,
}


def stage_load_data(state: PipelineState) -> PipelineState:
    """Fetch prices for the spec's universe, recording what we could not get."""
    spec = state.spec
    if spec is None:
        raise ValueError("no spec")

    asset_class = spec.universe.asset_class.value
    if spec.universe.tickers:
        tickers = spec.universe.tickers
    elif asset_class in UNIVERSE_TICKERS:
        tickers = UNIVERSE_TICKERS[asset_class]()
    else:
        state.errors.append(
            f"no universe configured for {asset_class.value}. "
            "Supported today: commodity futures, or explicit tickers in the spec."
        )
        return state

    state.prices, state.coverage = load_prices(tickers)

    if asset_class is AssetClass.COMMODITY_FUTURES:
        missing = unobtainable()
        if missing:
            state.errors.append(
                f"{len(missing)} of the paper's contracts have no free data source: "
                + ", ".join(c.name for c in missing)
            )
    return state


def stage_run_sandboxed(state: PipelineState, timeout: int = 60) -> PipelineState:
    """Execute the generated code in isolation."""
    if not state.code or state.prices is None or state.prices.empty:
        return state
    state.sandbox = run_generated_signal(state.code, state.prices, timeout=timeout)
    if not state.sandbox.ok:
        state.errors.append(f"sandboxed run failed: {state.sandbox.error}")
    return state


# --------------------------------------------------------------------------
# Stage 5 — audit
# --------------------------------------------------------------------------


def stage_audit(state: PipelineState) -> PipelineState:
    """Run the six checks and produce the verdict."""
    if state.spec is None or state.prices is None:
        raise ValueError("need a spec and prices to audit")

    state.variants_tested += 1
    generated = state.sandbox.signal if (state.sandbox and state.sandbox.ok) else None

    state.report = run_audit(
        state.prices,
        state.spec,
        generated_signal=generated,
        n_tests=state.variants_tested,
    )
    return state


# --------------------------------------------------------------------------
# Convenience: the whole thing, auto-confirming
# --------------------------------------------------------------------------


def run_full_pipeline(
    client: LLMClient,
    source: str | Path,
    *,
    auto_confirm: bool = False,
) -> PipelineState:
    """Run every stage. `auto_confirm` skips the human gate — tests only.

    In the product the gate is real; here it exists so the regression suite can
    exercise the whole path without a person in the loop.
    """
    state = PipelineState()
    stage_extract(state, client, source)

    if not auto_confirm:
        raise ValueError(
            "human confirmation is required. Call the stages individually, or "
            "pass auto_confirm=True in tests."
        )

    stage_confirm(state)
    stage_load_data(state)
    stage_generate(state, client)
    stage_run_sandboxed(state)
    stage_audit(state)
    return state
