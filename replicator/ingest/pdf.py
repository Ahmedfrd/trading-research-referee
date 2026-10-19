"""PDF loading: page texts plus sha256, with page markers for LLM prompts."""
from __future__ import annotations
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class PaperDocument:
    path: str
    sha256: str
    pages: list[str] = field(default_factory=list)

    def page(self, n: int) -> str:
        """1-based page text ('' if out of range)."""
        return self.pages[n - 1] if 1 <= n <= len(self.pages) else ""

    def _last_page(self) -> int:
        """Index (exclusive) after dropping pages from a final References heading onward."""
        pat = re.compile(r"^\s*(references|bibliography)\s*$", re.I | re.M)
        for i in range(len(self.pages) - 1, -1, -1):
            if pat.search(self.pages[i]):
                # only trust it in the back half of the paper
                return i + 1 if i >= len(self.pages) // 2 else len(self.pages)
        return len(self.pages)

    def text_with_markers(self, drop_references: bool = True) -> str:
        end = self._last_page() if drop_references else len(self.pages)
        return "\n".join(f"[[page {i + 1}]]\n{t}" for i, t in enumerate(self.pages[:end]))


def load_pdf(path: str | Path) -> PaperDocument:
    p = Path(path)
    raw = p.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    try:
        import pymupdf
        with pymupdf.open(stream=raw, filetype="pdf") as d:
            pages = [pg.get_text() for pg in d]
    except Exception:
        from pypdf import PdfReader
        pages = [pg.extract_text() or "" for pg in PdfReader(str(p)).pages]
    return PaperDocument(str(p), sha, pages)
