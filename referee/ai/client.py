"""The LLM backend, behind one small interface.

Everything upstream talks to `LLMClient`. Which model actually answers — the
Claude Code CLI running on a subscription, or the Messages API running on a
key — is a single swap here and nowhere else.

System prompts are not embedded in this file. They live as versioned Markdown
in `prompts/`, are passed explicitly on every call, and are displayed in the
UI. The prompt is part of the product, not a hidden implementation detail.
"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

log = logging.getLogger(__name__)

PROMPT_DIR = Path(__file__).resolve().parents[2] / "prompts"

# Claude Code loads its own tool manual into every call. We use none of those
# tools, and the manual is ~13k tokens of noise plus latency, so they are all
# switched off.
_UNUSED_TOOLS = [
    "Bash", "Edit", "Write", "Read", "Glob", "Grep",
    "WebFetch", "WebSearch", "Task", "TodoWrite", "NotebookEdit",
]


class LLMError(RuntimeError):
    """The model could not be reached, or returned nothing usable."""


@dataclass
class LLMResponse:
    text: str
    model: str = ""
    duration_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


class LLMClient(Protocol):
    """Anything that can answer a prompt under a system prompt."""

    def complete(self, system: str, user: str, *, timeout: int = 300) -> LLMResponse: ...


# --------------------------------------------------------------------------


class ClaudeCLIClient:
    """Backend: `claude -p`, the Claude Code CLI in headless mode.

    Authenticates with the user's existing subscription login — no API key.
    The trade-off versus the Messages API is that output cannot be constrained
    to a schema server-side, so callers must validate and retry. That is what
    `structured()` does.
    """

    def __init__(self, model: str = "sonnet", binary: str = "claude") -> None:
        self.model = model
        self.binary = binary

    def complete(self, system: str, user: str, *, timeout: int = 300) -> LLMResponse:
        cmd = [
            self.binary,
            "-p",
            "--model", self.model,
            "--output-format", "json",
            "--max-turns", "1",
            "--disable-slash-commands",
            "--strict-mcp-config",
            "--disallowedTools", *_UNUSED_TOOLS,
            "--system-prompt", system,
            user,
        ]

        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout, check=False
            )
        except FileNotFoundError as exc:
            raise LLMError(
                f"`{self.binary}` not found on PATH. Install the Claude Code CLI, "
                "or switch to the API backend."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise LLMError(f"model call exceeded {timeout}s") from exc

        if proc.returncode != 0:
            raise LLMError(
                f"CLI exited {proc.returncode}: {(proc.stderr or proc.stdout)[:400]}"
            )

        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise LLMError(f"CLI returned non-JSON: {proc.stdout[:400]}") from exc

        if payload.get("is_error"):
            raise LLMError(f"model error: {payload.get('result', 'unknown')}")

        usage = next(iter(payload.get("modelUsage", {}).values()), {})
        return LLMResponse(
            text=payload.get("result", ""),
            model=usage.get("canonicalModel", self.model),
            duration_ms=payload.get("duration_ms", 0),
            input_tokens=usage.get("inputTokens", 0),
            output_tokens=usage.get("outputTokens", 0),
        )


class ClaudeAPIClient:
    """Backend: the Messages API. Requires ANTHROPIC_API_KEY.

    Kept as a drop-in alternative. Structured outputs make extraction strictly
    more reliable here, so this is the upgrade path if a key becomes available.
    """

    def __init__(self, model: str = "claude-opus-5") -> None:
        try:
            import anthropic
        except ImportError as exc:
            raise LLMError("pip install anthropic to use the API backend") from exc
        self._client = anthropic.Anthropic()
        self.model = model

    def complete(self, system: str, user: str, *, timeout: int = 300) -> LLMResponse:
        msg = self._client.messages.create(
            model=self.model,
            max_tokens=16000,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = next((b.text for b in msg.content if b.type == "text"), "")
        return LLMResponse(
            text=text,
            model=msg.model,
            input_tokens=msg.usage.input_tokens,
            output_tokens=msg.usage.output_tokens,
        )


# --------------------------------------------------------------------------
# Prompts and structured output
# --------------------------------------------------------------------------


def load_prompt(name: str) -> str:
    """Read a versioned system prompt from `prompts/`."""
    path = PROMPT_DIR / f"{name}.md"
    if not path.exists():
        raise LLMError(f"no prompt named {name!r} in {PROMPT_DIR}")
    return path.read_text()


def extract_json(text: str) -> str:
    """Pull a JSON object out of a reply that may be wrapped in prose or fences."""
    body = text.strip()

    if "```" in body:
        start = body.find("```")
        fence_end = body.find("\n", start)
        closing = body.find("```", fence_end)
        if fence_end != -1 and closing != -1:
            body = body[fence_end + 1 : closing].strip()

    first, last = body.find("{"), body.rfind("}")
    if first == -1 or last <= first:
        raise LLMError(f"no JSON object found in reply: {text[:300]}")
    return body[first : last + 1]


def structured(
    client: LLMClient,
    system: str,
    user: str,
    model_cls: type,
    *,
    attempts: int = 3,
    timeout: int = 300,
):
    """Ask for JSON, validate it against a Pydantic model, retry on failure.

    This replaces the server-side schema enforcement the Messages API would
    give us. Each retry feeds the validation error back to the model, which in
    practice converges within one or two tries — and a failure that survives
    all attempts is raised loudly rather than papered over.
    """
    from pydantic import ValidationError

    question = user
    last_error = ""

    for attempt in range(1, attempts + 1):
        reply = client.complete(system, question, timeout=timeout)
        try:
            return model_cls.model_validate_json(extract_json(reply.text)), reply
        except (ValidationError, LLMError) as exc:
            last_error = str(exc)[:2000]
            log.warning("attempt %d/%d failed validation: %s", attempt, attempts,
                        last_error[:200])
            question = (
                f"{user}\n\n"
                f"--- Your previous reply was rejected ---\n"
                f"{last_error}\n\n"
                f"Return corrected JSON only. No prose, no markdown fences."
            )

    raise LLMError(
        f"Could not read this document into a valid strategy specification "
        f"after {attempts} attempts. This usually means it does not describe a "
        f"tradeable strategy, or describes one the schema cannot express.\n\n"
        f"Last validation error:\n{last_error}"
    )
