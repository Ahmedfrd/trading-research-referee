"""Extraction tests.

Stage 1 turns a PDF into a draft spec. Its output is never trusted — but it
must be well-formed, must not silently truncate a paper, and must fail loudly
on input it cannot read.
"""

from pathlib import Path

import pytest

from referee.ai.client import LLMError
from referee.ai.extract import MAX_CHARS, extract_spec, read_pdf, trim
from referee.papers import cross_sectional_momentum
from tests.conftest import FakeLLM

JT_PDF = Path("data/papers/jegadeesh_titman_1993.pdf")


# -- PDF reading -----------------------------------------------------------


@pytest.mark.slow
def test_reads_a_real_paper():
    if not JT_PDF.exists():
        pytest.skip("paper not downloaded; see data/papers/README.md")

    text = read_pdf(JT_PDF)
    assert len(text) > 20_000
    assert "[page 1]" in text, "page markers let a reviewer locate a quote"
    assert "Jegadeesh" in text or "momentum" in text.lower()


def test_a_missing_file_raises_rather_than_returning_empty():
    with pytest.raises(Exception):
        read_pdf("data/papers/does_not_exist.pdf")


def test_an_unreadable_pdf_explains_why(tmp_path):
    """A scanned paper has no text layer; say so instead of extracting nothing."""
    fake = tmp_path / "scan.pdf"
    fake.write_bytes(b"%PDF-1.4\n%%EOF\n")
    with pytest.raises(Exception):
        read_pdf(fake)


# -- trimming --------------------------------------------------------------


def test_short_papers_are_passed_through_untouched():
    text = "A short paper about momentum." * 10
    assert trim(text) == text


def test_long_papers_are_trimmed_to_the_budget():
    text = "filler sentence with no method words. " * 8000
    out = trim(text)
    assert len(out) <= MAX_CHARS
    assert len(out) < len(text)


def test_trimming_keeps_the_front_of_the_paper():
    """The strategy is nearly always defined early; references never matter."""
    head = "THE STRATEGY IS DEFINED HERE. "
    text = head + ("padding. " * 20000)
    assert head.strip() in trim(text)


def test_trimming_retains_methodology_paragraphs_from_later_sections():
    filler = "\n\n".join(["irrelevant padding text here." * 30] * 400)
    method = "We rebalance the portfolio monthly and assume transaction costs of 10 bps."
    out = trim(filler + "\n\n" + method + "\n\n" + filler)
    assert "rebalance" in out or "transaction cost" in out


# -- the extraction call ---------------------------------------------------


def test_extraction_returns_a_validated_spec():
    spec_json = cross_sectional_momentum().model_dump_json()
    client = FakeLLM([spec_json])

    spec, reply = extract_spec(client, "some paper text about momentum")

    assert spec.paper.year == 1993
    assert reply.model == "fake"


def test_the_schema_is_sent_to_the_model():
    """Without the schema the model is guessing at field names."""
    client = FakeLLM([cross_sectional_momentum().model_dump_json()])
    extract_spec(client, "paper text")

    _, user = client.calls[0]
    assert "schema" in user.lower()
    assert "strategy_type" in user and "signal_lag_days" in user


def test_the_paper_text_reaches_the_model():
    client = FakeLLM([cross_sectional_momentum().model_dump_json()])
    extract_spec(client, "DISTINCTIVE MARKER TEXT")
    assert "DISTINCTIVE MARKER TEXT" in client.calls[0][1]


def test_a_model_that_never_returns_valid_json_raises():
    client = FakeLLM(["nonsense"] * 3)
    with pytest.raises(LLMError, match="no valid output"):
        extract_spec(client, "paper text", attempts=3)
