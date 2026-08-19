"""Check that a spec's quotes actually appear in the paper.

Every non-assumed field claims a verbatim sentence as its evidence. Nothing
was checking that the sentence exists. This module does.

It was written after the tool's own author was caught fabricating nine of
thirteen quotes while hand-writing a reference spec — paraphrasing from memory
rather than copying from the paper. An AI can make the same mistake, and the
consequence is identical: a spec that looks sourced, reads as authoritative,
and cites sentences nobody wrote.

The check is deliberately generous about formatting (PDFs hyphenate across
line breaks, collapse whitespace oddly, and use curly quotes) and strict about
substance: the words must be in the document.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from pydantic import BaseModel

from referee.spec import Confidence, Sourced, StrategySpec

# A quote must match this fraction of its longest verbatim run to count as
# found. Below 1.0 because extracted PDF text drops the occasional character.
FRAGMENT_WORDS = 6


@dataclass
class QuoteCheck:
    path: str
    quote: str
    confidence: Confidence
    found: bool

    @property
    def status(self) -> str:
        return "verified" if self.found else "NOT IN PAPER"


def normalise(text: str) -> str:
    """Flatten PDF artefacts so real matches are not lost to formatting.

    Handles hyphenation across line breaks ("transac- tion" -> "transaction"),
    collapsed whitespace, and typographic quotes and dashes.
    """
    text = text.replace("’", "'").replace("‘", "'")
    text = text.replace("“", '"').replace("”", '"')
    text = text.replace("–", "-").replace("—", "-")
    text = re.sub(r"(\w)-\s+(\w)", r"\1\2", text)  # de-hyphenate line breaks
    text = re.sub(r"\s+", " ", text)
    return text.lower().strip()


def _appears_in(quote: str, haystack: str) -> bool:
    """True if the quote, or a distinctive run of it, is in the document."""
    q = normalise(quote)
    if not q:
        return False
    if q in haystack:
        return True

    # Papers get quoted with elisions and minor edits. Accept the quote if a
    # distinctive consecutive run of its words appears verbatim.
    words = q.split()
    if len(words) < FRAGMENT_WORDS:
        return q in haystack
    return any(
        " ".join(words[i : i + FRAGMENT_WORDS]) in haystack
        for i in range(len(words) - FRAGMENT_WORDS + 1)
    )


def _walk(model: BaseModel, path: str = ""):
    for name, value in model:
        here = f"{path}.{name}" if path else name
        if isinstance(value, Sourced):
            yield here, value
        elif isinstance(value, BaseModel):
            yield from _walk(value, here)


def verify_quotes(spec: StrategySpec, paper_text: str) -> list[QuoteCheck]:
    """Check every quoted field against the paper. Assumed fields are skipped."""
    haystack = normalise(paper_text)
    checks: list[QuoteCheck] = []

    for path, sourced in _walk(spec):
        if sourced.confidence is Confidence.ASSUMED or not sourced.quote.strip():
            continue
        checks.append(
            QuoteCheck(
                path=path,
                quote=sourced.quote,
                confidence=sourced.confidence,
                found=_appears_in(sourced.quote, haystack),
            )
        )
    return checks


def quote_fidelity(checks: list[QuoteCheck]) -> float:
    """Fraction of claimed quotes that genuinely appear in the paper."""
    return sum(c.found for c in checks) / len(checks) if checks else 1.0


def unverified(checks: list[QuoteCheck]) -> list[QuoteCheck]:
    return [c for c in checks if not c.found]
