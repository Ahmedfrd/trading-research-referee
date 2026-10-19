"""LLM access via the Claude Code CLI, with an on-disk cache and a usage log.

Command (verified live, haiku, 2-field schema; prompt on stdin):
  claude -p --output-format json --json-schema '<schema>' --model haiku --system-prompt '<sys>' \
         --tools "" --no-session-persistence --disable-slash-commands --setting-sources "" \
         --max-turns 4 < prompt.txt
Result JSON carries `structured_output`, `usage`, `duration_ms`, `total_cost_usd`.
"""
from __future__ import annotations
import hashlib
import json
import subprocess
import time
from pathlib import Path
from typing import Any, Protocol

ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = ROOT / "data" / "kb" / "llm_cache"
USAGE_LOG = ROOT / "reports" / "llm_usage.jsonl"


class LLMError(RuntimeError):
    pass


class LLM(Protocol):
    def call(self, role: str, system: str, user: str, schema: dict) -> tuple[dict, dict]: ...


def _log(row: dict, log_path: Path = USAGE_LOG) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a") as f:
        f.write(json.dumps(row) + "\n")


def cache_key(model: str, system: str, user: str, schema: dict) -> str:
    blob = json.dumps([model, system, user, schema], sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


class ClaudeCLI:
    def __init__(self, model: str = "sonnet", timeout: int = 600, max_turns: int = 4,
                 cache_dir: Path = CACHE_DIR, usage_log: Path = USAGE_LOG, use_cache: bool = True):
        self.model, self.timeout, self.max_turns = model, timeout, max_turns
        self.cache_dir, self.usage_log, self.use_cache = Path(cache_dir), Path(usage_log), use_cache

    def call(self, role: str, system: str, user: str, schema: dict) -> tuple[dict, dict]:
        key = cache_key(self.model, system, user, schema)
        cpath = self.cache_dir / f"{key}.json"
        if self.use_cache and cpath.exists():
            hit = json.loads(cpath.read_text())
            usage = {**hit.get("usage", {}), "cache_hit": True}
            self._record(role, usage)
            return hit["output"], usage
        cmd = ["claude", "-p", "--output-format", "json",
               "--json-schema", json.dumps(schema, separators=(",", ":")),
               "--model", self.model, "--system-prompt", system,
               "--tools", "", "--no-session-persistence", "--disable-slash-commands",
               "--setting-sources", "", "--max-turns", str(self.max_turns)]
        t0 = time.time()
        try:
            p = subprocess.run(cmd, input=user, capture_output=True, text=True, timeout=self.timeout)
        except FileNotFoundError as e:
            raise LLMError(
                "Claude CLI is not on PATH. Extraction uses a cached or fixture model output "
                "and does not start a live call.") from e
        except subprocess.TimeoutExpired as e:
            raise LLMError(f"claude timed out after {self.timeout}s") from e
        if p.returncode != 0:
            raise LLMError(f"claude exit {p.returncode}: {p.stderr[:500]} {p.stdout[:300]}")
        try:
            res = json.loads(p.stdout)
        except json.JSONDecodeError as e:
            raise LLMError(f"bad JSON from claude: {p.stdout[:300]}") from e
        out = res.get("structured_output")
        if not isinstance(out, dict):
            raise LLMError(f"no structured_output (subtype={res.get('subtype')}): "
                           f"{str(res.get('result'))[:300]} {p.stderr[:200]}")
        u = res.get("usage", {}) or {}
        usage = {
            "duration_ms": res.get("duration_ms", int((time.time() - t0) * 1000)),
            "input_tokens": u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
            + u.get("cache_read_input_tokens", 0),
            "output_tokens": u.get("output_tokens", 0),
            "cost_usd_if_reported": res.get("total_cost_usd"),
            "cache_hit": False,
        }
        if self.use_cache:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            cpath.write_text(json.dumps({"output": out, "usage": usage}))
        self._record(role, usage)
        return out, usage

    def _record(self, role: str, usage: dict) -> None:
        _log({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "role": role, "model": self.model,
              "duration_ms": usage.get("duration_ms", 0), "input_tokens": usage.get("input_tokens", 0),
              "output_tokens": usage.get("output_tokens", 0),
              "cost_usd_if_reported": usage.get("cost_usd_if_reported"),
              "cache_hit": usage.get("cache_hit", False)}, self.usage_log)


class FakeLLM:
    """Test double. responses: list of dicts (popped in order) or callable(role, system, user, schema)->dict."""
    def __init__(self, responses: Any):
        self.responses, self.calls = responses, []

    def call(self, role: str, system: str, user: str, schema: dict) -> tuple[dict, dict]:
        self.calls.append((role, system, user, schema))
        out = self.responses(role, system, user, schema) if callable(self.responses) else (
            self.responses.pop(0) if isinstance(self.responses, list) else self.responses)
        return out, {"duration_ms": 0, "input_tokens": 0, "output_tokens": 0,
                     "cost_usd_if_reported": None, "cache_hit": False}
