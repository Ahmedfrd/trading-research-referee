"""Shared fixtures.

The LLM is faked everywhere except the tests marked `live`. Tests that depend
on a model's mood are not tests — they are weather reports.
"""

import numpy as np
import pandas as pd
import pytest

from referee.ai.client import LLMResponse


class FakeLLM:
    """Returns scripted replies, and records what it was asked.

    Lets us test retry behaviour, prompt construction and error handling
    deterministically, without a network call or a subscription.
    """

    def __init__(self, replies: list[str]):
        self.replies = list(replies)
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str, *, timeout: int = 300) -> LLMResponse:
        self.calls.append((system, user))
        text = self.replies.pop(0) if self.replies else ""
        return LLMResponse(text=text, model="fake", duration_ms=1)


@pytest.fixture
def fake_llm():
    return FakeLLM


@pytest.fixture(scope="session")
def small_prices() -> pd.DataFrame:
    """A small, deterministic price panel for fast tests."""
    rng = np.random.default_rng(42)
    idx = pd.bdate_range("2015-01-01", periods=800)
    return pd.DataFrame(
        {
            f"T{i}": 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.009, len(idx))))
            for i in range(6)
        },
        index=idx,
    )


VALID_SIGNAL_CODE = """
import pandas as pd
import numpy as np

def compute_signal(prices: pd.DataFrame) -> pd.DataFrame:
    \"\"\"Trailing 60-day return.\"\"\"
    return prices / prices.shift(60) - 1
"""
