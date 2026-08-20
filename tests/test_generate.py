"""Code-generation and static-check tests.

The static check is the gate between a language model and `exec`. If it lets
look-ahead or a filesystem call through, the sandbox is the only thing left.
"""

import pytest

from referee.ai.client import LLMError
from referee.ai.generate import UnsafeCode, _strip_fences, check_code, generate_code
from referee.papers import cross_sectional_momentum
from tests.conftest import VALID_SIGNAL_CODE, FakeLLM


# -- look-ahead patterns ---------------------------------------------------


@pytest.mark.parametrize(
    "body,needle",
    [
        ("return prices.shift(-1)", "look-ahead"),
        ("return prices.shift(-30)", "look-ahead"),
        ("return prices.bfill()", "look-ahead"),
        ("return prices.backfill()", "look-ahead"),
    ],
)
def test_future_reading_code_is_rejected(body, needle):
    code = f"import pandas as pd\ndef compute_signal(prices):\n    {body}\n"
    problems = check_code(code)
    assert problems and any(needle in p for p in problems)


@pytest.mark.parametrize(
    "body",
    [
        "return prices.shift(1)",
        "return prices.rolling(20).mean()",
        "return prices.ewm(halflife=10).std()",
        "return prices.pct_change(60)",
        "return prices / prices.shift(252) - 1",
    ],
)
def test_backward_looking_code_is_allowed(body):
    """The check must not be so strict that correct code cannot pass."""
    code = f"import pandas as pd\ndef compute_signal(prices):\n    {body}\n"
    assert check_code(code) == []


# -- unsafe operations -----------------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        "import os",
        "import sys",
        "import subprocess",
        "from pathlib import Path",
        "import requests",
    ],
)
def test_imports_outside_the_allowlist_are_rejected(line):
    code = f"{line}\nimport pandas as pd\ndef compute_signal(prices):\n    return prices\n"
    assert any("not allowed" in p for p in check_code(code))


@pytest.mark.parametrize(
    "body",
    [
        "open('/etc/passwd')",
        "eval('1+1')",
        "exec('x=1')",
        "__import__('os')",
        "globals()",
        "getattr(prices, 'values')",
    ],
)
def test_dangerous_builtins_are_rejected(body):
    code = f"import pandas as pd\ndef compute_signal(prices):\n    {body}\n    return prices\n"
    assert any("not allowed" in p for p in check_code(code))


def test_dunder_access_is_rejected():
    code = "import pandas as pd\ndef compute_signal(prices):\n    return prices.__class__\n"
    assert any("__class__" in p for p in check_code(code))


def test_syntax_errors_are_reported_clearly():
    problems = check_code("def compute_signal(prices)\n    return prices")
    assert problems and "does not parse" in problems[0]


def test_missing_entry_point_is_reported():
    assert any("compute_signal" in p for p in check_code("import pandas as pd\nx = 1"))


# -- generation loop -------------------------------------------------------


def test_generation_returns_code_that_passes_the_checks():
    client = FakeLLM([VALID_SIGNAL_CODE])
    code, _ = generate_code(client, cross_sectional_momentum())
    assert "compute_signal" in code and check_code(code) == []


def test_generation_retries_and_feeds_the_error_back():
    """A rejected attempt must tell the model what was wrong, not just retry."""
    bad = "import pandas as pd\ndef compute_signal(prices):\n    return prices.shift(-1)\n"
    client = FakeLLM([bad, VALID_SIGNAL_CODE])

    code, _ = generate_code(client, cross_sectional_momentum())

    assert check_code(code) == []
    assert len(client.calls) == 2
    second_prompt = client.calls[1][1]
    assert "rejected" in second_prompt and "look-ahead" in second_prompt


def test_generation_gives_up_loudly_rather_than_shipping_unsafe_code():
    bad = "import os\ndef compute_signal(prices):\n    return prices\n"
    client = FakeLLM([bad, bad, bad])

    with pytest.raises(UnsafeCode, match="still unsafe"):
        generate_code(client, cross_sectional_momentum(), attempts=3)


def test_the_paper_text_is_never_sent_to_the_generator():
    """Code must come from the reviewed spec, never the raw paper."""
    client = FakeLLM([VALID_SIGNAL_CODE])
    spec = cross_sectional_momentum()
    generate_code(client, spec)

    _, user = client.calls[0]
    assert spec.paper.title in user or "compute_signal" in user
    assert "[page 1]" not in user, "raw PDF text leaked into the code prompt"


# -- fence stripping -------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "```python\ndef compute_signal(p):\n    return p\n```",
        "```\ndef compute_signal(p):\n    return p\n```",
        "def compute_signal(p):\n    return p",
    ],
)
def test_markdown_fences_are_stripped(raw):
    assert _strip_fences(raw).startswith("def compute_signal")
