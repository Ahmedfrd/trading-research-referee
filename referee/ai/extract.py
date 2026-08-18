"""Stage 1 of the pipeline: paper (PDF) -> StrategySpec.

The output of this stage is never trusted. It is shown to a human, who
confirms or corrects it, and only the confirmed spec proceeds to code
generation.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from referee.ai.client import LLMClient, LLMError, LLMResponse, load_prompt, structured
from referee.spec import StrategySpec

log = logging.getLogger(__name__)

# Papers are long and the strategy is almost always described early. Sending
# the whole thing is slow and dilutes attention, so we cap the excerpt.
MAX_CHARS = 60_000


def read_pdf(path: str | Path) -> str:
    """Extract text from a PDF."""
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages = []
    for i, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception as exc:  # a single unreadable page must not kill the run
            log.warning("page %d unreadable: %s", i, exc)
            continue
        if text.strip():
            pages.append(f"[page {i}]\n{text}")

    if not pages:
        raise LLMError(
            f"no extractable text in {path}. The PDF is probably a scan; "
            "this tool cannot read scanned papers."
        )
    return "\n\n".join(pages)


def trim(text: str, max_chars: int = MAX_CHARS) -> str:
    """Keep the front of the paper, plus anything that smells like methodology.

    The strategy definition is normally in the first third. References and
    appendices are the least useful text in the document.
    """
    text = re.sub(r"\n{3,}", "\n\n", text)
    if len(text) <= max_chars:
        return text

    head = text[: int(max_chars * 0.75)]
    tail_pool = text[int(max_chars * 0.75) :]

    keep = [
        para
        for para in tail_pool.split("\n\n")
        if re.search(
            r"\b(portfolio|rebalanc|transaction cost|Sharpe|weight|"
            r"long|short|decile|lookback|formation)\b",
            para,
            re.I,
        )
    ]
    remainder = max_chars - len(head)
    return head + "\n\n[...]\n\n" + "\n\n".join(keep)[:remainder]


def extract_spec(
    client: LLMClient,
    paper_text: str,
    *,
    attempts: int = 3,
) -> tuple[StrategySpec, LLMResponse]:
    """Read a paper into a spec, validating the reply against the schema."""
    system = load_prompt("extract_spec")
    schema = json.dumps(StrategySpec.model_json_schema(), indent=2)

    user = (
        "Extract the trading strategy from the paper below into JSON matching "
        "this schema.\n\n"
        f"## Schema\n```json\n{schema}\n```\n\n"
        f"## Paper\n{trim(paper_text)}"
    )

    spec, reply = structured(client, system, user, StrategySpec, attempts=attempts)
    log.info(
        "extracted %r in %dms (%d in / %d out tokens)",
        spec.paper.title, reply.duration_ms, reply.input_tokens, reply.output_tokens,
    )
    return spec, reply
