"""Run a generated strategy module under an import allowlist and a time limit.

The threat model (plan Phase 6) is code that is wrong or accidentally
destructive, not a hostile author. ``load`` therefore stays in this process:
the callable it returns is the strategy's ``run(returns, extra)``, and it sees
the caller's objects. A subprocess would isolate memory, but it would also
break that contract (live engine objects, in-process patches, the returned
``BacktestResult``).

Enforced here:
- an import from the generated module must name a module in ``ALLOWED_MODULES``
- direct calls to ``exec``, ``eval``, ``compile``, and ``__import__`` are rejected
- ``open`` is rejected for every path: the loader keeps the module in memory and
  has no output directory
- a wall-clock ``SIGALRM`` limit wraps the module body and each ``run`` call

``pandas`` itself is allowlisted, so helpers such as ``DataFrame.to_csv`` can
still touch the filesystem. The builtin ``open`` is what generated code cannot call.

Best-effort, not applied to the host process:
- ``resource.RLIMIT_AS``. On macOS ``setrlimit`` refuses to lower it
  (``ValueError: current limit exceeds maximum limit``). A cap that did stick
  would cover the UI and the pipeline, not just the strategy. ``RLIMIT_CPU``
  is the same kind of process-wide kill, so the wall-clock alarm is the limit
  that actually stops a runaway loop.

The allowlist is installed only on the generated module's builtins. Trusted
imports inside ``replicator.engine`` still use the normal importer, which is
how those helpers pull in the stdlib they need. Walking an imported function's
``__globals__`` to recover the real builtins is outside this sandbox.
"""
from __future__ import annotations

import ast
import builtins
import signal
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Callable

# Direct imports of the three template families in render._FAMILIES, plus numpy
# and pandas, which those engine helpers are written against. Submodules of
# numpy and pandas are allowed. Other project modules are not.
ALLOWED_MODULES = frozenset({
    "numpy",
    "pandas",
    "replicator.engine.portfolio",
    "replicator.engine.ml",
})

# Obvious escapes. These are rejected even though the allowlist would already
# exclude them, so a later prefix rule cannot reopen them by accident.
BLOCKED_ROOTS = frozenset({
    "subprocess", "multiprocessing", "socket", "ctypes", "shutil",
    "pickle", "shelve", "http", "urllib", "ssl", "ftplib", "smtplib",
    "webbrowser", "signal", "asyncio", "importlib", "runpy", "builtins",
    "sys", "os", "io", "pathlib", "pty", "fcntl", "mmap", "resource",
    "requests", "httpx", "urllib3",
})

# Escapes that live under an otherwise allowed library prefix.
DENIED_PREFIXES = ("numpy.ctypeslib", "numpy.f2py")

_BANNED_CALLS = frozenset({"exec", "eval", "compile", "__import__", "breakpoint", "input"})

_SAFE_BUILTINS = (
    "abs", "all", "any", "bool", "dict", "enumerate", "filter", "float",
    "frozenset", "globals", "int", "isinstance", "issubclass", "iter", "len",
    "list", "map", "max", "min", "next", "print", "range", "repr", "reversed",
    "round", "set", "slice", "sorted", "str", "sum", "tuple", "zip",
    "Exception", "ArithmeticError", "AssertionError", "AttributeError",
    "ImportError", "IndexError", "KeyError", "LookupError", "ModuleNotFoundError",
    "NameError", "NotImplementedError", "OSError", "OverflowError", "RuntimeError",
    "StopIteration", "TypeError", "ValueError", "ZeroDivisionError",
)

# Per call to run(), and again for the module body. Long enough for the
# random-feature template; a hung loop still dies.
DEFAULT_TIMEOUT = 300.0

_REAL_IMPORT = builtins.__import__
_LIBRARY_ROOTS = frozenset({"numpy", "pandas"})


class SandboxError(Exception):
    """Generated code broke the sandbox (import, file, or call)."""


class SandboxTimeout(SandboxError):
    """The wall-clock limit fired while generated code was running."""


def import_block_reason(name: object, fromlist: object = ()) -> str | None:
    """Why ``name`` (and any ``fromlist`` entries) may not be imported, or None."""
    if not isinstance(name, str) or not name or name.startswith("."):
        return f"import of {name!r} is blocked in the sandbox"
    if _is_blocked(name):
        return f"import of {name!r} is blocked in the sandbox"
    if not _is_allowlisted(name):
        return f"import of {name!r} is not on the sandbox allowlist"
    items = _from_items(fromlist)
    if items is None:
        return f"import of {name!r} is blocked in the sandbox"
    for item in items:
        if item == "*":
            return f"star import of {name!r} is blocked in the sandbox"
        if not isinstance(item, str):
            return f"import of {name!r} is blocked in the sandbox"
        child = f"{name}.{item}"
        if _is_blocked(child):
            return f"import of {child!r} is blocked in the sandbox"
    return None


def find_violations(source: str) -> list[str]:
    """Static rejects: disallowed imports and calls that bypass the import hook."""
    tree = ast.parse(source)
    found: list[str] = []
    for node in ast.walk(tree):
        found.extend(_violations_at(node))
    return found


def memory_limit_available() -> bool:
    """Whether a child can lower ``RLIMIT_AS``.

    Best-effort only. macOS rejects the cap, and ``load`` does not apply it in
    this process: a limit that stuck would cover the host application too.
    The probe runs in a child so a successful cap cannot shrink this process.
    """
    probe = (
        "import resource, sys\n"
        "cap = 256 * 1024 * 1024\n"
        "try:\n"
        "    hard = resource.getrlimit(resource.RLIMIT_AS)[1]\n"
        "    ceiling = cap if hard == resource.RLIM_INFINITY else min(cap, hard)\n"
        "    resource.setrlimit(resource.RLIMIT_AS, (ceiling, hard))\n"
        "except (ValueError, OSError):\n"
        "    sys.exit(2)\n"
        "sys.exit(0)\n"
    )
    try:
        proc = subprocess.run(
            [sys.executable, "-I", "-c", probe],
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def load_source(source: str, *, timeout: float | None = None) -> Callable[..., Any]:
    """Execute ``source`` under the allowlist and return its ``run(returns, extra)``."""
    limit = _timeout_seconds(timeout)
    violations = find_violations(source)
    if violations:
        raise SandboxError("generated code was rejected by the sandbox:\n" + "\n".join(violations))
    namespace = _namespace()

    def _execute() -> None:
        exec(compile(source, "<generated_strategy>", "exec"), namespace)

    _call_with_timeout(_execute, limit)
    inner = namespace.get("run")
    if not callable(inner):
        raise SandboxError("generated module has no run() function")

    def run(returns, extra):
        return _call_with_timeout(lambda: inner(returns, extra), limit)

    return run


def _is_blocked(name: str) -> bool:
    root = name.split(".", 1)[0]
    if root in BLOCKED_ROOTS:
        return True
    return any(name == prefix or name.startswith(prefix + ".") for prefix in DENIED_PREFIXES)


def _is_allowlisted(name: str) -> bool:
    if name in ALLOWED_MODULES:
        return True
    root = name.split(".", 1)[0]
    return root in _LIBRARY_ROOTS and root in ALLOWED_MODULES and name.startswith(root + ".")


def _from_items(fromlist: object) -> tuple[Any, ...] | None:
    if fromlist is None:
        return ()
    if isinstance(fromlist, str):
        return (fromlist,)
    try:
        return tuple(fromlist)
    except TypeError:
        return None


def _violations_at(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Import):
        return _import_violations(node)
    if isinstance(node, ast.ImportFrom):
        return _import_from_violations(node)
    if isinstance(node, ast.Call):
        called = _called_name(node.func)
        if called in _BANNED_CALLS:
            return [f"line {node.lineno}: {called}() is blocked in the sandbox"]
    return []


def _import_violations(node: ast.Import) -> list[str]:
    found = []
    for alias in node.names:
        reason = import_block_reason(alias.name)
        if reason:
            found.append(f"line {alias.lineno}: {reason}")
    return found


def _import_from_violations(node: ast.ImportFrom) -> list[str]:
    if node.level:
        return [f"line {node.lineno}: relative imports are blocked in the sandbox"]
    reason = import_block_reason(node.module or "", [alias.name for alias in node.names])
    if reason:
        return [f"line {node.lineno}: {reason}"]
    return []


def _called_name(func: ast.AST) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    return None


def _guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    if level:
        raise SandboxError(f"relative import is blocked in the sandbox (level {level})")
    reason = import_block_reason(name, fromlist)
    if reason:
        raise SandboxError(reason)
    return _REAL_IMPORT(name, globals, locals, fromlist, level)


def _guarded_open(file, mode="r", *args, **kwargs):
    writing = any(flag in str(mode) for flag in ("w", "a", "x", "+"))
    kind = "write" if writing else "read"
    try:
        shown: object = Path(file).expanduser()
    except TypeError:
        shown = file
    raise SandboxError(
        f"file {kind} is blocked in the sandbox ({shown}); generated code has no output directory"
    )


def _namespace() -> dict:
    sandbox_builtins = {name: getattr(builtins, name) for name in _SAFE_BUILTINS}
    sandbox_builtins["__import__"] = _guarded_import
    sandbox_builtins["open"] = _guarded_open
    return {"__name__": "generated_strategy", "__builtins__": sandbox_builtins}


def _timeout_seconds(timeout: float | None) -> float:
    limit = DEFAULT_TIMEOUT if timeout is None else float(timeout)
    if limit != limit or limit <= 0 or limit == float("inf"):
        raise SandboxError("sandbox timeout must be a positive finite number of seconds")
    return limit


def _call_with_timeout(fn: Callable[[], Any], timeout: float) -> Any:
    """Run ``fn`` on the main thread, raising ``SandboxTimeout`` when ``timeout`` elapses."""
    if threading.current_thread() is not threading.main_thread() or not hasattr(signal, "SIGALRM"):
        raise SandboxError("sandbox timeout requires the main thread and SIGALRM")
    message = f"execution exceeded {timeout:g}s and was stopped"

    def _handler(signum, frame):
        raise SandboxTimeout(message)

    previous = signal.signal(signal.SIGALRM, _handler)
    previous_timer = signal.setitimer(signal.ITIMER_REAL, timeout)
    try:
        return fn()
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
        if previous_timer[0] > 0:
            signal.setitimer(signal.ITIMER_REAL, previous_timer[0])
