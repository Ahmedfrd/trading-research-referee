"""Sandbox tests.

The sandbox exists to run code written by a language model. The threat model
is *wrong* code — infinite loops, wrong shapes, accidental file access — not a
determined attacker. These tests pin the behaviour that matters for that.
"""

import numpy as np
import pandas as pd
import pytest

from referee.engine.sandbox import _describe_exit, run_generated_signal
from tests.conftest import VALID_SIGNAL_CODE


@pytest.fixture(scope="module")
def prices() -> pd.DataFrame:
    idx = pd.bdate_range("2020-01-01", periods=300)
    return pd.DataFrame(
        {"A": np.linspace(100, 200, 300), "B": np.linspace(200, 150, 300)}, index=idx
    )


def test_valid_code_runs_and_returns_a_signal(prices):
    r = run_generated_signal(VALID_SIGNAL_CODE, prices, timeout=30)
    assert r.ok, r.error
    assert r.signal.shape == prices.shape
    assert list(r.signal.columns) == list(prices.columns)


@pytest.mark.parametrize(
    "module",
    ["socket", "urllib", "subprocess", "shutil", "ctypes", "requests", "pickle"],
)
def test_network_and_system_imports_are_blocked(prices, module):
    code = f"""
import pandas as pd
def compute_signal(prices):
    import {module}
    return prices
"""
    r = run_generated_signal(code, prices, timeout=30)
    assert not r.ok
    assert "blocked" in r.error.lower() or module in r.error


def test_infinite_loop_is_killed(prices):
    code = """
import pandas as pd
def compute_signal(prices):
    while True:
        pass
"""
    r = run_generated_signal(code, prices, timeout=6)
    assert not r.ok
    assert r.duration_s < 20, "the timeout must actually bound the run"


def test_wrong_row_count_is_rejected(prices):
    code = """
import pandas as pd
def compute_signal(prices):
    return prices.iloc[:10]
"""
    r = run_generated_signal(code, prices, timeout=30)
    assert not r.ok and "rows" in r.error


def test_wrong_columns_are_rejected(prices):
    code = """
import pandas as pd
def compute_signal(prices):
    out = prices.copy()
    out.columns = ['X', 'Y']
    return out
"""
    r = run_generated_signal(code, prices, timeout=30)
    assert not r.ok and "columns" in r.error


def test_non_dataframe_return_is_rejected(prices):
    code = """
import pandas as pd
def compute_signal(prices):
    return 42
"""
    r = run_generated_signal(code, prices, timeout=30)
    assert not r.ok and "DataFrame" in r.error


def test_runtime_error_is_reported_not_swallowed(prices):
    code = """
import pandas as pd
def compute_signal(prices):
    return prices + does_not_exist
"""
    r = run_generated_signal(code, prices, timeout=30)
    assert not r.ok and "does_not_exist" in r.error


def test_missing_entry_point_is_rejected(prices):
    r = run_generated_signal("import pandas as pd\nx = 1\n", prices, timeout=30)
    assert not r.ok


def test_the_parent_process_survives_a_crash(prices):
    """A crash in generated code must not take the app down with it."""
    code = """
import pandas as pd
def compute_signal(prices):
    raise SystemExit(1)
"""
    r = run_generated_signal(code, prices, timeout=30)
    assert not r.ok  # and we are still here to assert it


def test_exit_codes_are_described_in_english():
    assert "CPU" in _describe_exit(-24)
    assert "memory" in _describe_exit(-9).lower()
    assert "status 3" in _describe_exit(3)
