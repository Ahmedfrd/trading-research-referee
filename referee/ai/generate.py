"""Stage 3 of the pipeline: StrategySpec -> executable Python.

Generated code is checked statically before it is ever executed. The checks
here are the first half of the sandbox: they reject look-ahead bias and unsafe
operations by reading the code's syntax tree, so bad code never reaches the
subprocess at all.
"""

from __future__ import annotations

import ast
import logging

from referee.ai.client import LLMClient, LLMError, LLMResponse, load_prompt
from referee.spec import StrategySpec

log = logging.getLogger(__name__)

ALLOWED_IMPORTS = {"pandas", "numpy"}

# Attribute calls that read forward in time. `.shift()` is handled separately
# because it is only unsafe with a negative argument.
LOOKAHEAD_CALLS = {
    "bfill": "backward-fills from future rows",
    "backfill": "backward-fills from future rows",
}

# Anything that could touch the outside world.
FORBIDDEN_NAMES = {
    "open", "exec", "eval", "compile", "__import__", "input",
    "globals", "locals", "vars", "getattr", "setattr", "delattr",
}


class UnsafeCode(Exception):
    """Generated code failed a static check. It is not executed."""


def _describe(node: ast.AST) -> str:
    return f"line {getattr(node, 'lineno', '?')}"


def check_code(source: str) -> list[str]:
    """Static safety and look-ahead audit. Returns a list of violations."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [f"does not parse: {exc}"]

    problems: list[str] = []

    for node in ast.walk(tree):
        # -- imports
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root not in ALLOWED_IMPORTS:
                    problems.append(f"{_describe(node)}: import of {root!r} not allowed")
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root not in ALLOWED_IMPORTS:
                problems.append(f"{_describe(node)}: import from {root!r} not allowed")

        # -- dangerous builtins
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            problems.append(f"{_describe(node)}: use of {node.id!r} not allowed")

        # -- dunder access, the usual sandbox escape
        elif isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            problems.append(f"{_describe(node)}: attribute {node.attr!r} not allowed")

        # -- look-ahead
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            name = node.func.attr
            if name in LOOKAHEAD_CALLS:
                problems.append(
                    f"{_describe(node)}: .{name}() {LOOKAHEAD_CALLS[name]} (look-ahead)"
                )
            elif name == "shift":
                for arg in list(node.args) + [kw.value for kw in node.keywords]:
                    if (
                        isinstance(arg, ast.UnaryOp)
                        and isinstance(arg.op, ast.USub)
                        and isinstance(arg.operand, ast.Constant)
                    ):
                        problems.append(
                            f"{_describe(node)}: .shift(-{arg.operand.value}) "
                            "reads future rows (look-ahead)"
                        )

    if "def compute_signal" not in source:
        problems.append("no compute_signal function defined")

    return problems


def generate_code(
    client: LLMClient,
    spec: StrategySpec,
    *,
    attempts: int = 3,
) -> tuple[str, LLMResponse]:
    """Generate a signal function from the spec, retrying on failed checks.

    The spec is passed as JSON, and the paper is not passed at all — code must
    be derived from the reviewed artefact, not the raw source.
    """
    system = load_prompt("generate_code")
    spec_json = spec.model_dump_json(indent=2)

    user = (
        "Write the `compute_signal` function for this strategy specification.\n\n"
        f"```json\n{spec_json}\n```"
    )

    last_problems: list[str] = []
    for attempt in range(1, attempts + 1):
        reply = client.complete(system, user)
        code = _strip_fences(reply.text)
        problems = check_code(code)

        if not problems:
            log.info("generated %d lines, passed static checks", len(code.splitlines()))
            return code, reply

        last_problems = problems
        log.warning("attempt %d/%d rejected: %s", attempt, attempts, problems)
        user = (
            f"Write the `compute_signal` function for this strategy specification.\n\n"
            f"```json\n{spec_json}\n```\n\n"
            f"--- Your previous code was rejected ---\n"
            + "\n".join(f"- {p}" for p in problems)
            + "\n\nReturn corrected code only."
        )

    raise UnsafeCode(
        f"generated code still unsafe after {attempts} attempts:\n"
        + "\n".join(f"  - {p}" for p in last_problems)
    )


def _strip_fences(text: str) -> str:
    body = text.strip()
    if body.startswith("```"):
        first_newline = body.find("\n")
        closing = body.rfind("```")
        if first_newline != -1 and closing > first_newline:
            body = body[first_newline + 1 : closing]
    return body.strip()
