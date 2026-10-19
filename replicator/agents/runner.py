"""Cached model calls for agent roles.

The runner uses the Claude CLI when it is on PATH, an on-disk cache, or a fixture
directory. It does not start a live process when the CLI is missing, so a demo and
the tests finish instead of waiting on a model.
"""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

from replicator.extract.llm import ClaudeCLI, LLMError

_RATE = ("rate limit", "usage limit", "overloaded", "429")


def claude_on_path() -> bool:
    return shutil.which("claude") is not None


def fixture_file(role: str) -> Path | None:
    """JSON file for ``role`` when REPLICATOR_LLM_FIXTURES points at a directory."""
    raw = os.environ.get("REPLICATOR_LLM_FIXTURES", "").strip()
    if not raw:
        return None
    path = Path(raw) / f"{role}.json"
    return path if path.is_file() else None


def _rate_limited(message: str) -> bool:
    text = message.lower()
    return any(bit in text for bit in _RATE)


class RecordingLLM:
    """Forwards calls and keeps token and time for the agent trace."""

    def __init__(self, inner):
        self.inner = inner
        self.events: list[dict] = []

    def call(self, role: str, system: str, user: str, schema: dict) -> tuple[dict, dict]:
        out, usage = self.inner.call(role, system, user, schema)
        self.events.append({
            "role": role,
            "duration_ms": int(usage.get("duration_ms") or 0),
            "input_tokens": int(usage.get("input_tokens") or 0),
            "output_tokens": int(usage.get("output_tokens") or 0),
            "cache_hit": bool(usage.get("cache_hit")),
        })
        return out, usage


class Runner:
    """LLM protocol. Pass an inner model (tests use FakeLLM); otherwise use cache, fixtures, or the CLI."""

    def __init__(self, llm=None, model: str = "sonnet", models: dict | None = None):
        self._llm = llm
        self.model = model
        self.models = dict(models or {})
        self.events: list[dict] = []

    def call(self, role: str, system: str, user: str, schema: dict) -> tuple[dict, dict]:
        last_error: LLMError | None = None
        for attempt in range(2):
            try:
                out, usage = self._once(role, system, user, schema)
            except LLMError as exc:
                last_error = exc
                if attempt == 0 and _rate_limited(str(exc)):
                    time.sleep(1.0)
                    continue
                raise
            self.events.append({
                "role": role,
                "duration_ms": int(usage.get("duration_ms") or 0),
                "input_tokens": int(usage.get("input_tokens") or 0),
                "output_tokens": int(usage.get("output_tokens") or 0),
                "cache_hit": bool(usage.get("cache_hit")),
            })
            return out, usage
        raise last_error or LLMError("The model step did not finish.")

    def _once(self, role: str, system: str, user: str, schema: dict) -> tuple[dict, dict]:
        if self._llm is not None:
            return self._llm.call(role, system, user, schema)
        found = fixture_file(role)
        if found is not None:
            out = json.loads(found.read_text(encoding="utf-8"))
            usage = {"duration_ms": 0, "input_tokens": 0, "output_tokens": 0,
                     "cost_usd_if_reported": None, "cache_hit": True}
            return out, usage
        if not claude_on_path():
            raise LLMError(
                "Claude CLI is not on PATH. Extraction uses a cached or fixture model output "
                "and does not start a live call.")
        model = self.models.get(role, self.model)
        try:
            return ClaudeCLI(model).call(role, system, user, schema)
        except FileNotFoundError as exc:
            raise LLMError(
                "Claude CLI is not on PATH. Extraction uses a cached or fixture model output "
                "and does not start a live call.") from exc
