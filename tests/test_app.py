"""Streamlit interface tests.

The UI had no coverage at all, which is how a `None` reached a format string
and crashed the Verdict tab on any strategy that lost money in both periods.
The audit layer was fully tested; the screen that renders it was not.

These drive the real app through `AppTest` — clicking the actual buttons, in
the order a reviewer would — so a change to the data contract underneath
fails here rather than in front of someone.

They are marked slow: each one boots the app and loads real price history.
"""

from pathlib import Path

import pytest

from referee.spec import Confidence, StrategySpec

ROOT = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.slow

streamlit_testing = pytest.importorskip("streamlit.testing.v1")
AppTest = streamlit_testing.AppTest

APP = str(ROOT / "app.py")
TIMEOUT = 300


def _boot() -> "AppTest":
    at = AppTest.from_file(APP, default_timeout=TIMEOUT)
    at.run()
    assert not at.exception, at.exception
    return at


def _button(at, label):
    return next((b for b in at.button if b.label == label), None)


def _markdown(at) -> str:
    return " ".join(m.value for m in at.markdown)


def _approve_code(at) -> None:
    """Stand in for the tab-3 approval, which needs a live model call.

    Code generation is the one step these tests cannot drive — it shells out
    to the CLI. Setting the two fields it would have set keeps the rest of the
    path honest: the audit still refuses unless `code_approved` is true.
    """
    at.session_state.pipeline.code = "def compute_signal(prices):\n    return prices"
    at.session_state.pipeline.code_approved = True
    at.run()


def test_the_app_boots_with_opus_as_the_default_model():
    """Extraction is the step everything downstream inherits its errors from."""
    at = _boot()
    model = at.sidebar.selectbox[0]
    assert model.value == "opus"
    assert model.options[0] == "opus"


def test_a_reference_paper_reaches_a_verdict():
    """The whole non-AI path: load, confirm, load data, audit."""
    at = _boot()

    _button(at, "Load reference specification").click().run()
    assert not at.exception, at.exception
    assert at.session_state.pipeline.spec is not None

    _button(at, "I have reviewed this specification").click().run()
    assert not at.exception, at.exception
    assert at.session_state.pipeline.spec_confirmed

    load = _button(at, "Load data and audit")
    if load:
        load.click().run()
        assert not at.exception, at.exception

    _approve_code(at)
    _button(at, "Run the audit").click().run()
    assert not at.exception, at.exception

    report = at.session_state.pipeline.report
    assert report is not None
    assert report.verdict.value in {"REPLICATES", "WEAKENED", "FAILS", "NOT_TESTABLE"}


def test_the_confirm_tab_writes_the_strategy_out_in_full():
    """A reviewer approving a strategy needs the whole strategy, not a summary."""
    at = _boot()
    _button(at, "Load reference specification").click().run()

    body = _markdown(at)
    for section in (
        "The universe",
        "The signal",
        "From score to position",
        "Position sizing",
        "Timing and execution",
        "Transaction costs",
        "The claim being tested",
    ):
        assert section in body, f"missing section: {section}"


def test_the_confirm_tab_reports_data_problems_not_only_reading_problems():
    """Jegadeesh & Titman traded the NYSE; we have 108 names. Say so."""
    at = _boot()
    _button(at, "Load reference specification").click().run()

    warnings = " ".join(w.value for w in at.warning)
    assert "1000 assets" in warnings and "108" in warnings


def test_a_correction_is_applied_recorded_and_does_not_launder_provenance():
    """The reviewer may overrule the extractor; the edit is what gets tested."""
    at = _boot()
    _button(at, "Load reference specification").click().run()

    field = at.session_state.pipeline.spec.signal.lookback_days
    assert field.value == 252

    widget = next(
        n for n in at.number_input if n.key == "edit::signal.lookback_days"
    )
    widget.set_value(126).run()
    _button(at, "Apply corrections").click().run()
    assert not at.exception, at.exception

    spec = at.session_state.pipeline.spec
    assert spec.signal.lookback_days.value == 126, "the correction must take effect"
    assert spec.signal.lookback_days.confidence is not Confidence.EXPLICIT, (
        "a human correction is not a citation — the paper still does not "
        "state this field, and promoting it would launder an assumption"
    )
    assert any("Reviewer correction" in n for n in spec.extraction_notes), (
        "the change must travel with the spec, not live only in the session"
    )
    assert at.session_state.pipeline.spec_confirmed is False, (
        "editing the spec withdraws the approval of the version before it"
    )


def test_an_untestable_paper_is_told_exactly_why():
    """A refusal is only useful if it names the thing that stopped it."""
    at = _boot()

    spec = StrategySpec.model_validate_json(
        (ROOT / "data/cache/spec_arxiv_2302.13245v1.json").read_text()
    )
    at.session_state.pipeline.spec = spec
    at.session_state.pipeline.spec_confirmed = True
    at.run()

    _button(at, "Load data and audit").click().run()
    assert not at.exception, at.exception

    report = at.session_state.pipeline.report
    assert report.verdict.value == "NOT_TESTABLE"

    errors = " ".join(e.value for e in at.error)
    assert "Why this paper could not be tested" in errors
    assert "hk_equities" in errors, "the reason must name this paper's problem"
    assert "The universe" in _markdown(at), (
        "the reader should still see what would have been tested"
    )


def test_the_verdict_shows_the_claim_beside_the_measurement():
    """The gap between advertised and delivered is the product's whole point."""
    at = _boot()
    _button(at, "Load reference specification").click().run()
    _button(at, "I have reviewed this specification").click().run()

    load = _button(at, "Load data and audit")
    if load:
        load.click().run()
    _approve_code(at)
    _button(at, "Run the audit").click().run()
    assert not at.exception, at.exception

    body = _markdown(at)
    assert "Claimed against measured" in body
    assert "Performance against the claim" in body


def test_generated_code_is_not_runnable_until_approved_in_the_ui():
    """The code gate must be reachable and closed by default.

    Code generation needs the model, so this asserts the gate's resting
    state rather than driving a live call: with no code present there is
    nothing to approve, and approval never survives into a fresh session.
    """
    at = _boot()
    _button(at, "Load reference specification").click().run()
    _button(at, "I have reviewed this specification").click().run()

    s = at.session_state.pipeline
    assert s.code == ""
    assert s.code_approved is False
    assert _button(at, "Generate code") is not None, (
        "the code tab should offer generation once the spec is confirmed"
    )


def test_the_audit_will_not_run_until_the_code_has_been_approved():
    """A verdict is a claim that we implemented the right strategy.

    The only evidence for that is a second implementation someone has read.
    Reaching the verdict without one leaves the cross-engine check
    permanently N/A and the number resting on a single unreviewed reading of
    the spec.
    """
    at = _boot()
    _button(at, "Load reference specification").click().run()
    _button(at, "I have reviewed this specification").click().run()

    load = _button(at, "Load data and audit")
    if load:
        load.click().run()

    run = _button(at, "Run the audit")
    assert run is not None and run.disabled, "the audit must be blocked"
    assert any("No code generated yet" in w.value for w in at.warning), (
        "and it must say why, with the tab to fix it in"
    )
    assert at.session_state.pipeline.report is None

    _approve_code(at)
    run = _button(at, "Run the audit")
    assert not run.disabled, "approval must unlock it"
    run.click().run()
    assert at.session_state.pipeline.report is not None


def test_an_untestable_paper_still_refuses_without_any_code():
    """The refusal path must not be caught by the code gate.

    There is nothing to implement for a paper whose universe we cannot even
    resolve, so demanding an implementation first would deadlock the one
    answer the tool can honestly give.
    """
    at = _boot()
    spec = StrategySpec.model_validate_json(
        (ROOT / "data/cache/spec_arxiv_2302.13245v1.json").read_text()
    )
    at.session_state.pipeline.spec = spec
    at.session_state.pipeline.spec_confirmed = True
    at.run()

    _button(at, "Load data and audit").click().run()
    assert not at.exception, at.exception

    s = at.session_state.pipeline
    assert s.code_approved is False, "no code was ever written"
    assert s.report.verdict.value == "NOT_TESTABLE"


def test_the_cross_engine_check_can_be_skipped_but_never_silently():
    """The demo escape hatch.

    Gating the verdict on code approval makes every answer depend on a model
    call. When the model is slow or unreachable, five checks with the sixth
    declared is more useful than no answer — but only if the omission is on
    the card rather than hidden in an N/A nobody reads.
    """
    at = _boot()
    _button(at, "Load reference specification").click().run()
    _button(at, "I have reviewed this specification").click().run()
    load = _button(at, "Load data and audit")
    if load:
        load.click().run()

    assert _button(at, "Run the audit").disabled, "the gate is still the default"

    hatch = next(c for c in at.checkbox if "cross-engine" in c.label)
    assert hatch.value is False, "opting out must be deliberate"

    hatch.check().run()
    run = _button(at, "Run the audit")
    assert not run.disabled
    run.click().run()
    assert not at.exception, at.exception

    s = at.session_state.pipeline
    assert s.code_approved is False, "the hatch must not fake an approval"
    assert s.report is not None

    cross = next(
        c for c in s.report.checks if c.name == "Cross-engine agreement"
    )
    assert cross.status == "N/A" and not cross.passed, (
        "a skipped check must never read as a pass"
    )
    assert any("skipped at the operator" in n for n in s.report.notes), (
        "the verdict must say a check was dropped, and why"
    )
