"""Execute generated code in an isolated subprocess.

## What this actually guarantees, and what it does not

Guaranteed:
  - a separate process, so a crash or hang cannot take down the app
  - a hard wall-clock timeout
  - CPU-time and address-space limits, so a runaway loop or allocation dies
  - Python's isolated mode, so the parent's environment is not inherited
  - an import hook that refuses any module outside the allowlist, which
    blocks `socket`, `urllib`, `subprocess` and friends at import time
  - a static AST check (see `referee.ai.generate.check_code`) that runs first

Not guaranteed:
  - true kernel-level isolation. A determined escape from a Python-level
    import hook is possible. Full isolation needs a container.

That limitation is stated rather than papered over. The threat model here is
*AI-generated code that is wrong or accidentally destructive*, not a hostile
attacker, and for that threat model this is proportionate.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 60
MEMORY_LIMIT_MB = 2048

_HARNESS = '''
import resource, sys, builtins

# Best-effort: macOS refuses RLIMIT_AS outright, so a failure here must not
# abort the run. The wall-clock timeout in the parent is the backstop that
# always applies.
for _limit, _value in ((resource.RLIMIT_CPU, {cpu}), (resource.RLIMIT_AS, {mem})):
    try:
        _soft, _hard = resource.getrlimit(_limit)
        _cap = _value if _hard == resource.RLIM_INFINITY else min(_value, _hard)
        resource.setrlimit(_limit, (_cap, _hard))
    except (ValueError, OSError):
        pass

ALLOWED = {{
    "pandas", "numpy", "math", "datetime", "itertools", "functools",
    "collections", "typing", "operator", "warnings", "dateutil", "pytz",
    "zoneinfo", "decimal", "numbers", "abc", "copy", "enum", "re", "json",
    "_strptime", "encodings", "importlib", "pkgutil", "types", "inspect",
    "textwrap", "contextlib", "traceback", "weakref", "threading", "time",
    "struct", "array", "bisect", "heapq", "random", "hashlib", "unicodedata",
    "string", "io", "os", "os.path", "posixpath", "gc", "platform", "sysconfig",
}}
BLOCKED = {{
    "socket", "urllib", "http", "ftplib", "smtplib", "telnetlib", "ssl",
    "subprocess", "multiprocessing", "shutil", "ctypes", "pickle", "shelve",
    "webbrowser", "requests", "httpx", "urllib3", "asyncio", "signal",
}}

_real_import = builtins.__import__

def _guarded(name, *args, **kwargs):
    root = name.split(".")[0]
    if root in BLOCKED:
        raise ImportError(f"import of {{name!r}} is blocked in the sandbox")
    return _real_import(name, *args, **kwargs)

import pandas as pd
import numpy as np
builtins.__import__ = _guarded

prices = pd.read_parquet({prices!r})

namespace = {{"pd": pd, "np": np}}
exec(open({code!r}).read(), namespace)

signal = namespace["compute_signal"](prices)

if not isinstance(signal, pd.DataFrame):
    raise TypeError(f"compute_signal returned {{type(signal).__name__}}, expected DataFrame")
if list(signal.columns) != list(prices.columns):
    raise ValueError("returned columns do not match the price columns")
if len(signal) != len(prices):
    raise ValueError(f"returned {{len(signal)}} rows, expected {{len(prices)}}")

builtins.__import__ = _real_import
signal.to_parquet({out!r})
'''


@dataclass
class SandboxResult:
    ok: bool
    signal: pd.DataFrame | None = None
    error: str = ""
    duration_s: float = 0.0


def run_generated_signal(
    code: str,
    prices: pd.DataFrame,
    *,
    timeout: int = DEFAULT_TIMEOUT,
) -> SandboxResult:
    """Run `compute_signal` from `code` against `prices`, in a subprocess."""
    import time

    with tempfile.TemporaryDirectory(prefix="referee-") as tmp:
        tmp = Path(tmp)
        code_path, prices_path = tmp / "strategy.py", tmp / "prices.parquet"
        out_path, harness_path = tmp / "signal.parquet", tmp / "harness.py"

        code_path.write_text(code)
        prices.to_parquet(prices_path)
        harness_path.write_text(
            _HARNESS.format(
                cpu=timeout,
                mem=MEMORY_LIMIT_MB * 1024 * 1024,
                prices=str(prices_path),
                code=str(code_path),
                out=str(out_path),
            )
        )

        started = time.monotonic()
        try:
            proc = subprocess.run(
                [sys.executable, "-I", str(harness_path)],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=tmp,
                env={"PATH": "/usr/bin:/bin", "HOME": str(tmp)},
            )
        except subprocess.TimeoutExpired:
            return SandboxResult(
                ok=False,
                error=f"execution exceeded {timeout}s and was killed",
                duration_s=time.monotonic() - started,
            )

        elapsed = time.monotonic() - started

        if proc.returncode != 0:
            return SandboxResult(
                ok=False,
                error=_last_traceback_line(proc.stderr) or _describe_exit(proc.returncode),
                duration_s=elapsed,
            )

        if not out_path.exists():
            return SandboxResult(
                ok=False, error="produced no output", duration_s=elapsed
            )

        return SandboxResult(
            ok=True, signal=pd.read_parquet(out_path), duration_s=elapsed
        )


def _last_traceback_line(stderr: str) -> str:
    """The exception line, not the whole traceback — that is what a user reads."""
    lines = [ln for ln in (stderr or "").strip().splitlines() if ln.strip()]
    if not lines:
        return ""
    for line in reversed(lines):
        if not line.startswith((" ", "\t")) and ":" in line:
            return line.strip()
    return lines[-1].strip()


def _describe_exit(code: int) -> str:
    """Turn a subprocess exit code into something a user can act on."""
    if code >= 0:
        return f"exited with status {code}"
    signals = {
        -24: "killed: exceeded its CPU time limit (likely an infinite loop)",
        -9: "killed: exceeded memory or was force-terminated",
        -11: "crashed with a segmentation fault",
    }
    return signals.get(code, f"killed by signal {-code}")
