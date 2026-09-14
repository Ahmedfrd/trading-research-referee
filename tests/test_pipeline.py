"""Pipeline orchestration tests.

The stages exist separately because stage 2 is a human. These tests pin the
gate: no code may be generated from an unreviewed spec.
"""

import pandas as pd
import pytest

from referee.ai.client import LLMError
from referee.papers import cross_sectional_momentum, time_series_momentum
from referee.pipeline import (
    PipelineState,
    stage_approve_code,
    stage_audit,
    stage_confirm,
    stage_generate,
    stage_load_data,
    stage_run_sandboxed,
)
from tests.conftest import VALID_SIGNAL_CODE, FakeLLM


def test_code_generation_is_blocked_until_a_human_confirms():
    """The guard rail the whole design rests on."""
    state = PipelineState()
    state.spec = cross_sectional_momentum()
    assert not state.spec_confirmed

    with pytest.raises(ValueError, match="confirmed by a human"):
        stage_generate(state, FakeLLM([VALID_SIGNAL_CODE]))


def test_confirmation_unlocks_generation():
    state = PipelineState()
    state.spec = cross_sectional_momentum()
    stage_confirm(state)

    stage_generate(state, FakeLLM([VALID_SIGNAL_CODE]))
    assert "compute_signal" in state.code
    assert state.errors == []


def test_confirming_nothing_is_an_error():
    with pytest.raises(ValueError, match="nothing to confirm"):
        stage_confirm(PipelineState())


def test_confirmation_can_replace_a_corrected_spec():
    """The reviewer may edit the spec; the edit must be what proceeds."""
    state = PipelineState()
    state.spec = cross_sectional_momentum()

    corrected = time_series_momentum()
    stage_confirm(state, corrected)

    assert state.spec is corrected and state.spec_confirmed


def test_generation_failure_is_recorded_not_raised():
    """A bad model reply must surface in the UI, not crash the app."""
    state = PipelineState()
    state.spec = cross_sectional_momentum()
    stage_confirm(state)

    stage_generate(state, FakeLLM(["import os\ndef compute_signal(p): return p"] * 3))
    assert state.code == "" and state.errors


def test_sandbox_stage_is_a_no_op_without_code(small_prices):
    state = PipelineState()
    state.prices = small_prices
    stage_run_sandboxed(state)
    assert state.sandbox is None


def test_audit_requires_a_spec_and_prices():
    with pytest.raises(ValueError, match="need a spec"):
        stage_audit(PipelineState())


def test_each_audit_raises_the_multiple_testing_bar(small_prices):
    """Every run counts as a variant tried. Fiddling must cost something."""
    state = PipelineState()
    state.spec = time_series_momentum()
    state.prices = small_prices

    bars = []
    for _ in range(3):
        stage_audit(state)
        check = next(c for c in state.report.checks if c.name == "Multiple testing")
        bars.append(check.data["adjusted_bar"])

    assert state.variants_tested == 3
    assert bars == sorted(bars) and bars[0] < bars[-1]


def test_unknown_universe_is_reported_rather_than_guessed():
    from referee.spec import AssetClass, Sourced

    state = PipelineState()
    state.spec = time_series_momentum()
    state.spec.universe.asset_class = Sourced(
        value=AssetClass.CRYPTO, quote="bitcoin and friends"
    )
    stage_load_data(state)

    assert state.errors and "no universe configured" in state.errors[0]


@pytest.mark.slow
def test_full_pipeline_from_confirmed_spec_to_verdict(small_prices):
    """Stages 2 through 5 wired together, with a scripted model."""
    state = PipelineState()
    state.spec = time_series_momentum()
    state.prices = small_prices

    stage_confirm(state)
    stage_generate(state, FakeLLM([VALID_SIGNAL_CODE]))
    stage_approve_code(state)
    stage_run_sandboxed(state)
    stage_audit(state)

    assert state.sandbox.ok, state.sandbox.error
    assert state.report is not None
    cross = next(c for c in state.report.checks if c.name == "Cross-engine agreement")
    assert cross.applicable, "generated code should have been compared to the engine"


def test_an_unsupported_asset_class_refuses_instead_of_crashing():
    """No data is a reason to refuse, not a reason to raise.

    A paper on Indian equities extracts to an asset class with no configured
    universe, so it reached the audit with `prices` still unset and raised
    ValueError — in the UI, a button that silently did nothing.
    """
    from referee.audit.verdict import Verdict
    from referee.spec import AssetClass, Sourced

    state = PipelineState()
    state.spec = time_series_momentum()
    state.spec.universe.asset_class = Sourced(
        value=AssetClass.HK_EQUITIES, quote="stocks listed in Hong Kong"
    )
    stage_confirm(state)
    stage_load_data(state)
    stage_audit(state)

    assert state.prices is None
    assert state.report is not None, "the audit must produce a report, not raise"
    assert state.report.verdict is Verdict.NOT_TESTABLE
    assert "no universe configured" in state.report.reason


def test_generated_code_cannot_run_until_a_human_approves_it():
    """The second gate: safe code that computes the wrong thing.

    The spec gate catches a misread paper. This one catches a misread spec —
    code that passes the static check, runs clean, and implements something
    other than the strategy under review.
    """
    from referee.pipeline import stage_approve_code

    state = PipelineState()
    state.spec = time_series_momentum()
    state.prices = pd.DataFrame(
        {"A": [1.0] * 100, "B": [2.0] * 100},
        index=pd.bdate_range("2020-01-01", periods=100),
    )
    stage_confirm(state)
    stage_generate(state, FakeLLM([VALID_SIGNAL_CODE]))

    assert state.code, "code should have been generated"
    assert state.code_approved is False, "fresh code is not pre-approved"

    with pytest.raises(ValueError, match="approved by a human"):
        stage_run_sandboxed(state)

    stage_approve_code(state)
    stage_run_sandboxed(state)
    assert state.sandbox is not None


def test_regenerating_code_withdraws_the_previous_approval():
    """Approval belongs to the code that was read, not to the session."""
    from referee.pipeline import stage_approve_code

    state = PipelineState()
    state.spec = time_series_momentum()
    stage_confirm(state)
    stage_generate(state, FakeLLM([VALID_SIGNAL_CODE, VALID_SIGNAL_CODE]))
    stage_approve_code(state)
    assert state.code_approved is True

    stage_generate(state, FakeLLM([VALID_SIGNAL_CODE]))
    assert state.code_approved is False, (
        "new code must be re-read; carrying the flag over would run an "
        "unreviewed function on the strength of reviewing its predecessor"
    )


# -- extraction caching -----------------------------------------------------


def test_a_second_extraction_of_the_same_pdf_reuses_the_first(tmp_path, monkeypatch):
    """Three minutes a paper is not a price worth paying twice.

    The reuse must be visible, though: a cached spec presented as a fresh
    reading would be the tool lying about its own provenance.
    """
    from referee import pipeline
    from referee.papers import cross_sectional_momentum

    monkeypatch.setattr(pipeline, "SPEC_CACHE_DIR", tmp_path)
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr(pipeline, "read_pdf", lambda p: "the paper text")

    calls = []

    def fake_extract(client, text):
        calls.append(text)
        return cross_sectional_momentum(), None

    monkeypatch.setattr(pipeline, "extract_spec", fake_extract)

    first = PipelineState()
    pipeline.stage_extract(first, FakeLLM([]), pdf)
    assert len(calls) == 1, "the first read must actually happen"
    assert first.spec_from_cache is False
    assert pipeline.cached_spec_path(pdf).exists(), "and must be written down"

    second = PipelineState()
    pipeline.stage_extract(second, FakeLLM([]), pdf)
    assert len(calls) == 1, "the second must not call the model again"
    assert second.spec_from_cache is True, "and must admit it was reused"
    assert second.spec.paper.title == first.spec.paper.title


def test_the_cache_can_be_bypassed(tmp_path, monkeypatch):
    from referee import pipeline
    from referee.papers import cross_sectional_momentum

    monkeypatch.setattr(pipeline, "SPEC_CACHE_DIR", tmp_path)
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr(pipeline, "read_pdf", lambda p: "the paper text")

    calls = []
    monkeypatch.setattr(
        pipeline, "extract_spec",
        lambda c, t: (calls.append(t), (cross_sectional_momentum(), None))[1],
    )

    pipeline.stage_extract(PipelineState(), FakeLLM([]), pdf)
    state = PipelineState()
    pipeline.stage_extract(state, FakeLLM([]), pdf, use_cache=False)

    assert len(calls) == 2
    assert state.spec_from_cache is False


def test_a_corrupt_cache_falls_back_to_extracting(tmp_path, monkeypatch):
    """A bad cache file must not be able to stop the tool working."""
    from referee import pipeline
    from referee.papers import cross_sectional_momentum

    monkeypatch.setattr(pipeline, "SPEC_CACHE_DIR", tmp_path)
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr(pipeline, "read_pdf", lambda p: "the paper text")
    pipeline.cached_spec_path(pdf).write_text("{ this is not valid json")

    monkeypatch.setattr(
        pipeline, "extract_spec", lambda c, t: (cross_sectional_momentum(), None)
    )

    state = PipelineState()
    pipeline.stage_extract(state, FakeLLM([]), pdf)
    assert state.spec is not None and state.spec_from_cache is False


def test_quotes_are_reverified_even_on_a_cached_spec(tmp_path, monkeypatch):
    """The cache stores a reading, not a verification.

    If the document changed under a cached spec, the quotes stop matching and
    the reviewer must be told — otherwise stale provenance would look current.
    """
    from referee import pipeline
    from referee.papers import cross_sectional_momentum

    monkeypatch.setattr(pipeline, "SPEC_CACHE_DIR", tmp_path)
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr(pipeline, "read_pdf", lambda p: "the original paper text")
    monkeypatch.setattr(
        pipeline, "extract_spec", lambda c, t: (cross_sectional_momentum(), None)
    )

    pipeline.stage_extract(PipelineState(), FakeLLM([]), pdf)

    # The document is replaced; the cached spec's quotes no longer appear.
    monkeypatch.setattr(pipeline, "read_pdf", lambda p: "something else entirely")
    state = PipelineState()
    pipeline.stage_extract(state, FakeLLM([]), pdf)

    assert state.spec_from_cache is True
    assert state.quote_checks, "verification must still run"
    assert state.errors, "and must report quotes that are no longer in the text"
