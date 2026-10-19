"""Sandbox for generated strategy modules.

Allowed template code still loads and runs in-process. A disallowed import is
rejected, and a runaway ``run`` is stopped by the wall-clock limit.
"""
import sys
import time

import numpy as np
import pandas as pd
import pytest

from replicator.codegen.render import GeneratedCode, load, render
from replicator.codegen.sandbox import (
    ALLOWED_MODULES,
    SandboxError,
    SandboxTimeout,
    memory_limit_available,
)
from replicator.engine.portfolio import cross_sectional_jk
from replicator.spec.model import F, StrategySpec
from tests.rp.test_codegen import jt_spec


def _code(source: str) -> GeneratedCode:
    return GeneratedCode(source, {}, "x", "x")


def test_allowlist_is_the_template_imports():
    assert ALLOWED_MODULES == frozenset({
        "numpy", "pandas", "replicator.engine.portfolio", "replicator.engine.ml",
    })


def test_each_template_family_loads():
    assert callable(load(render(jt_spec())))
    series = StrategySpec(family="time_series_momentum")
    series.params.lookback = F(value=12, status="stated")
    assert callable(load(render(series)))
    timing = StrategySpec(family="ml_market_timing")
    timing.params.ml_train_window = F(value=12, status="stated")
    assert callable(load(render(timing)))
    factor = StrategySpec(family="factor_sort_2x3")
    factor.params.formation_periods = F(value=11, status="stated")
    assert callable(load(render(factor)))


def test_template_run_matches_the_engine():
    fn = load(render(jt_spec()))
    idx = pd.date_range("2000-01-31", periods=40, freq="ME")
    returns = pd.DataFrame(
        np.random.default_rng(0).normal(0, 0.02, (40, 6)), index=idx, columns=list("ABCDEF"),
    )
    out = fn(returns, {})
    direct = cross_sectional_jk(
        returns, J=12, K=3, skip=0, top_fraction=0.1, direction="long_short", cost_bps=0.0, lag=0,
    )
    pd.testing.assert_series_equal(out.returns, direct.returns)


def test_run_sees_the_caller_objects():
    fn = load(_code("def run(returns, extra):\n    extra['seen'] = returns\n    return returns\n"))
    sentinel = object()
    extra: dict = {}
    assert fn(sentinel, extra) is sentinel
    assert extra["seen"] is sentinel


@pytest.mark.parametrize("statement,text", [
    ("import socket", "socket"),
    ("import subprocess", "subprocess"),
    ("import ctypes", "ctypes"),
    ("import numpy.ctypeslib", "ctypeslib"),
    ("from numpy import ctypeslib", "ctypeslib"),
    ("import replicator.pipeline", "allowlist"),
])
def test_disallowed_import_is_rejected(statement, text):
    source = f"{statement}\ndef run(returns, extra):\n    return 1\n"
    with pytest.raises(SandboxError, match=text):
        load(_code(source))


def test_runtime_import_hook_blocks_a_dynamic_import():
    # No Import node and no direct __import__() call, so the static scan does
    # not see this. The hook on the generated module's builtins has to reject it.
    source = (
        "def run(returns, extra):\n"
        "    return globals()['__builtins__']['__import__']('socket')\n"
    )
    fn = load(_code(source))
    with pytest.raises(SandboxError, match="socket"):
        fn(None, {})


@pytest.mark.parametrize("mode", ["w", "r"])
def test_file_access_is_blocked(tmp_path, mode):
    target = tmp_path / "escape.txt"
    target.write_text("secret")
    source = (
        "def run(returns, extra):\n"
        f"    handle = open({str(target)!r}, {mode!r})\n"
        "    handle.close()\n"
        "    return 1\n"
    )
    fn = load(_code(source))
    with pytest.raises(SandboxError, match="file"):
        fn(None, {})
    assert target.read_text() == "secret"


def test_infinite_loop_is_stopped():
    fn = load(_code("def run(returns, extra):\n    while True:\n        pass\n"), timeout=2)
    started = time.monotonic()
    with pytest.raises(SandboxTimeout):
        fn(None, {})
    assert time.monotonic() - started < 10
    # The alarm must not still be armed.
    quick = load(_code("def run(returns, extra):\n    return 1\n"), timeout=5)
    assert quick(None, {}) == 1


def test_numpy_and_pandas_imports_are_allowed():
    source = (
        "import numpy as np\n"
        "import pandas as pd\n"
        "def run(returns, extra):\n"
        "    return int(np.int64(1) + len(pd.Series([1])))\n"
    )
    assert load(_code(source))(None, {}) == 2


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS rejects RLIMIT_AS")
def test_memory_limit_is_unavailable_on_macos():
    assert memory_limit_available() is False
