# Replicator v2: build design (2026-10-19 sprint)

This is the interface contract every build agent codes against. It is a condensed version of plan §4–§9, cut down
for a one-day build. Python 3.13, pandas 3, numpy 2. New package `replicator/`; the old `referee/` stays untouched (v0).

## Conventions (all modules)

- **No silent fills.** Missing data stays `NaN` and is recorded in a `GapReport`. Never use `ffill` or `fillna(0)`
  on returns or prices; the only exception is weights of assets not held, which are 0 by definition.
- **Returns** are simple decimal returns per period. **Index:** month-end `Timestamp` for monthly data, trading day for daily.
- **Point in time.** A position held during period `s` may use only data up to the end of period `s-1`.
- **Tests:**
  - live in `tests/rp/`
  - make no network or LLM calls (use `FakeLLM`; mark anything else `@pytest.mark.network` or `@pytest.mark.llm`)
  - test synthetic data against *known answers*
  - run with: `.venv/bin/python -m pytest tests/rp -q`
- **Style:** type hints; short docstrings stating conventions; comments only where something is non-obvious.

## Package map

```
replicator/
  config.py                 paths (written)
  data/provenance.py        DataProvenance, GapReport, sha256_file
  data/prices.py            Panel, load_price_panel, available_tickers   (offline: data/cache/prices/*.parquet)
  data/universes.py         Universe, UNIVERSES, get_universe
  data/reference.py         kf_ff3, kf_umd, kf_momentum_deciles, aqr_tsmom, goyal_welch_monthly
  metrics.py                perf_stats, newey_west_t, to_monthly, PERIODS_PER_YEAR
  engine/pit.py             causality harness used by checks
  engine/portfolio.py       BacktestResult, cross_sectional_jk, tsmom, ewma_vol_annualized, benchmark_equal_weight
  engine/ml.py              random-feature ridge market timing (KMZ), walk-forward, seeds
  checks/six.py             CheckResult + the six checks
  spec/model.py             StrategySpec v2 (pydantic) + JSON Schema
  ingest/pdf.py             PaperDocument, load_pdf
  extract/llm.py            ClaudeCLI (claude -p --json-schema), FakeLLM, cache, usage log
  extract/extract.py        extract_spec
  extract/citations.py      verify_citations
  extract/explain.py        strategy_page
  codegen/render.py         spec -> traceable Python module (template families)
  golden/{jt,tsmom,umd,kmz}.py  golden-set runs -> reports/golden/*.json
  kb/store.py               SQLite knowledge base (versioned)
  ui/app.py                 Streamlit app
```

## data

```python
@dataclass(frozen=True)
class DataProvenance:
    source: str; url: str | None; retrieved_at: str; vintage: str | None
    sha256: str | None; adjustments: str; license: str; known_biases: tuple[str, ...] = ()

class GapReport:                       # never fills, only records
    def add(self, asset: str, start, end, n: int, kind: str, action: str) -> None
      # kind: "missing_price" | "nonpositive_price" | "missing_return_while_held" | "insufficient_history"
      # action: "excluded" | "left_missing"
    def to_frame(self) -> pd.DataFrame
    def summary(self) -> str            # one line, e.g. "37 gaps across 12 assets; nothing filled"

@dataclass
class Panel:
    returns: pd.DataFrame               # dates x assets, NaN = unavailable
    freq: str                           # "D" or "M"
    provenance: list[DataProvenance]
    gaps: GapReport
    disclosures: list[str]              # survivorship etc., shown with every result

def available_tickers() -> list[str]    # decoded from cache filenames ('_eq_'->'=', '_idx_'->'^')
def load_price_panel(tickers: list[str], start=None, end=None, freq: str = "M") -> Panel
    # offline; daily close -> monthly = last close of month / previous month's last close - 1;
    # a month is NaN if either close is missing; non-positive prices dropped and recorded.

@dataclass
class Universe:
    key: str; label: str; asset_class: str; tickers: list[str]
    survivorship: str; notes: list[str]
UNIVERSES: dict[str, Universe]   # "us_equities_cached", "us_large_cap_v0", "commodity_futures_yahoo"
def get_universe(key: str) -> Universe

def kf_ff3() -> tuple[pd.DataFrame, DataProvenance]          # Mkt-RF, SMB, HML, RF (monthly decimals)
def kf_umd() -> tuple[pd.Series, DataProvenance]
def kf_momentum_deciles(weighting: str = "ew") -> tuple[pd.DataFrame, DataProvenance]  # cols D1..D10 (D10 = winners)
def aqr_tsmom() -> tuple[pd.DataFrame, DataProvenance]       # data/cache/aqr_tsmom_monthly.xlsx, sheet "TSMOM Factors", header=17
def goyal_welch_monthly() -> tuple[pd.DataFrame, DataProvenance]  # data/reference/goyal_welch_monthly.csv
```

Ken French CSVs are in percent. Divide by 100, map -99.99 / -999 to NaN and record each in the GapReport.
The files are in `data/reference/kf_*.zip`.

## metrics

```python
PERIODS_PER_YEAR = {"D": 252, "M": 12}
def perf_stats(r: pd.Series, freq: str, rf: pd.Series | None = None, turnover: pd.Series | None = None) -> dict
  # keys: n, start, end, mean, ann_mean (arithmetic mean*ppy), cagr, ann_vol (ddof=1), sharpe
  #       (excess over rf when rf given, flag sharpe_is_excess), t_stat, t_stat_nw, max_drawdown
  #       (equity starts at 1.0), hit_rate, ann_turnover
def newey_west_t(r: pd.Series, lags: int | None = None) -> float   # statsmodels HAC; default lags floor(4*(n/100)**(2/9))
def to_monthly(r_daily: pd.Series | pd.DataFrame)                  # compounded within month, NaN if no data
```

Cross-check against `empyrical` (sharpe_ratio, max_drawdown, annual_volatility, cagr) and `statsmodels`,
with any convention differences documented in the tests.

## engine

```python
@dataclass
class BacktestResult:
    returns: pd.Series            # net, per period
    gross: pd.Series
    weights: pd.DataFrame         # held during period s, decided with data up to end of s-1
    turnover: pd.Series           # sum |w_s - drifted w_{s-1}|
    costs: pd.Series
    meta: dict                    # params, breadth per date, n_cohorts, gaps (GapReport), notes

def cross_sectional_jk(returns: pd.DataFrame, J: int, K: int, skip: int = 0, top_fraction: float = 0.1,
                       direction: str = "long_short", min_per_leg: int = 1, cost_bps: float = 0.0,
                       lag: int = 0) -> BacktestResult
```

`cross_sectional_jk` follows Jegadeesh & Titman (1993):
- **Formation.** At the end of period `t`, rank assets on their cumulative return over periods `(t-skip-J, t-skip]`.
  An asset needs all J returns present and must be investable at `t`. No future information is used to choose assets.
- **Legs.** Long the top `round(n*top_fraction)` (at least `min_per_leg`), short the same count from the bottom.
  Within a leg, assets are equal-weighted.
- **Holding.** Each cohort is held for periods `t+1 .. t+K`. The portfolio in period `s` is the equal average of the
  cohorts formed at `s-1 .. s-K`. Output starts once all K cohorts exist.
- **Missing returns.** A held asset with a NaN return in period `s` is dropped from that period's leg average and
  recorded as `missing_return_while_held`. It is never filled.
- **Long/short return.** Long-leg mean minus short-leg mean, i.e. $1 long and $1 short.
- **Costs.** `turnover * cost_bps / 1e4`, one-way, on traded notional.
- **Lag.** `lag` shifts weights by extra periods (execution delay).

```python
def ewma_vol_annualized(daily_returns: pd.DataFrame, com: float = 60, min_periods: int = 60, ann: int = 261) -> pd.DataFrame
def tsmom(monthly_returns: pd.DataFrame, vol_ann_monthly: pd.DataFrame, lookback: int = 12,
          vol_target: float = 0.40, cost_bps: float = 0.0) -> BacktestResult
```

`tsmom` follows Moskowitz, Ooi & Pedersen (2012):
- `w_{i,s} = sign(cum return over the lookback months ending s-1) * vol_target / vol_{i,s-1}`.
- The portfolio return is the mean over the S assets that have a position.
- `vol_ann_monthly` is the daily EWMA volatility sampled at month-end.

```python
def benchmark_equal_weight(returns: pd.DataFrame, cost_bps: float = 0.0) -> BacktestResult
    # long-only, equal weight over the assets available each period, same data and same cost rate
```

`engine/pit.py`:

```python
def causality_report(strategy: Callable[[pd.DataFrame], pd.Series | pd.DataFrame], data: pd.DataFrame,
                     cuts: Sequence[int] | None = None, seed: int = 0) -> dict
    # truncation: output on data[:cut] equals output on full data over the shared index (allclose, NaN-aware)
    # perturbation: multiply data after cut by a random factor; output up to cut unchanged
    # returns {"truncation_ok": bool, "perturbation_ok": bool, "max_abs_diff": float, "cuts": [...]}
```

`engine/ml.py` (KMZ):

```python
def random_fourier_features(X: np.ndarray, P: int, gamma: float, seed: int) -> np.ndarray
def kmz_timing(gw: pd.DataFrame, P: int, T: int = 12, z: float = 1e3, gamma: float = 2.0, seeds: int = 10,
               standardize: str = "expanding") -> pd.DataFrame
    # walk-forward: at month t, fit ridge on the previous T months (features dated t-1 predict return t),
    # forecast t+1; strategy return = forecast * excess return. Columns: forecast, ret, strategy. Seed-averaged.
```

## checks

```python
@dataclass
class CheckResult:
    name: str; status: str            # "pass" | "fail" | "warn" | "n/a"
    headline: str; details: dict; method: str; cross_check: dict | None = None

check_lookahead(strategy, data) -> CheckResult                                 # wraps engine.pit.causality_report
check_replication(ours: float, ours_se: float | None, paper: float, paper_t: float | None = None,
                  paper_se: float | None = None, label: str = "") -> CheckResult
    # pass if |ours - paper| <= 2*sqrt(se_o^2 + se_p^2) AND same sign AND same significance at 5% (|t| > 1.96)
check_costs(gross: pd.Series, turnover: pd.Series, freq: str, grid_bps=(0, 5, 10, 20, 30, 50, 75, 100),
            assumed_bps: float | None = None) -> CheckResult      # net table, break-even bps (interpolated)
check_significance(r: pd.Series, freq: str, n_trials: int = 1, trial_sharpes: list[float] | None = None) -> CheckResult
    # Newey-West t; Bonferroni bar for n_trials; Harvey-Liu-Zhu t>3 flag; probabilistic + deflated Sharpe (Bailey & Lopez de Prado)
check_out_of_sample(r: pd.Series, freq: str, sample_start, sample_end, pub_year: int, min_periods: int = 24) -> CheckResult
    # in-sample (paper's own window) vs post-sample vs post-publication: means, t-stats, Sharpe; n/a if a window < min_periods
check_parameter_sensitivity(run: Callable[[dict], pd.Series], base: dict, grid: dict[str, list], freq: str) -> CheckResult
    # table of Sharpe/t per variant; plateau score = share of variants with same sign as base and |t| > 1.96
```

## spec / extraction / codegen

The spec v2 field wrapper is `F[T] = {value, status: stated|derived|assumed|unknown, citations: [{page:int, quote:str}],
note: str, approved: bool}`.

`StrategySpec` sections:
- **paper:** title, authors, year, venue, pdf_sha256, sample_start, sample_end
- **family:** `cross_sectional_jk | time_series_momentum | ml_market_timing | unsupported`
- **variants**
- **universe:** asset_class, description, n_assets, exchanges
- **data:** frequency
- **params:** formation_periods J, skip_periods, holding_periods K, top_fraction, direction, weighting, lookback,
  vol_target, ml fields
- **execution:** lag_periods, cost_bps
- **benchmark**
- **reported_results:** a list of `{id, variant_id, metric, value, units, period, gross_or_net, risk_adjustment,
  t_stat, table, row, col, page, quote}`
- **schema_fit** and **notes**

`extract/llm.py`: `ClaudeCLI(model).call(role, system, user, schema) -> (dict, usage)`.
- It runs `claude -p --output-format json --json-schema <schema> --model <m> --system-prompt <s>` and reads `structured_output`.
- Results are cached under `data/kb/llm_cache/<sha256>.json`.
- Every call is appended to `reports/llm_usage.jsonl` with `ts, role, model, duration_ms, input_tokens, output_tokens, cache_hit`.
- `FakeLLM` has the same interface, for tests.

`codegen/render.py`: `render(spec) -> GeneratedCode(source, bindings, family)`.
- Each template family maps to an engine function.
- Every parameter in the generated module carries a `# spec: <path>` comment.
- `validate(gen)` checks that every binding is used and that no unbound numeric literal remains.
- `family == unsupported` is refused with the reason.

## Wave 2: knowledge base, codegen, pipeline (the service layer the UI calls)

```python
# replicator/kb/store.py   (SQLite at data/kb/kb.sqlite; artifacts under data/kb/)
class KB:
    def __init__(self, path: Path | None = None)
    add_paper(pdf_path, doc: PaperDocument) -> int          # dedupe by sha256; copy PDF to data/kb/papers/<sha>.pdf
    list_papers() -> pd.DataFrame
    add_spec(paper_id, spec: StrategySpec, source: str, parent_id: int | None = None, note: str = "") -> int
        # source: "extracted" | "approved" | "edited"; version auto-increments per paper
    get_spec(spec_id) -> StrategySpec; list_specs(paper_id) -> pd.DataFrame; baseline_spec_id(paper_id) -> int | None  # first "approved"
    add_code(spec_id, gen: GeneratedCode) -> int; get_code(code_id) -> GeneratedCode
    add_run(spec_id, code_id, universe: str, params: dict, summary: dict, artifacts: dict[str, pd.DataFrame | pd.Series]) -> int
    list_runs(paper_id: int | None = None) -> pd.DataFrame; get_run(run_id) -> dict; count_runs(paper_id) -> int
    save_page(spec_id, page: dict); get_page(spec_id) -> dict | None
    add_note(paper_id, text); list_notes(paper_id)

# replicator/codegen/render.py
@dataclass
class GeneratedCode:
    source: str; bindings: dict[str, dict]; family: str; sha256: str   # bindings: spec_path -> {name, value}
class Unsupported(Exception)
render(spec: StrategySpec) -> GeneratedCode       # deterministic template rendering, no LLM; every constant carries "# spec: <path>"
validate(gen) -> list[str]                        # every binding used; no unbound numeric literal in run(); ast parses
load(gen) -> Callable[[pd.DataFrame, dict], BacktestResult]   # exec in a fresh namespace; source imports only replicator.engine

# replicator/pipeline.py
@dataclass
class RunOutcome:
    family: str; universe: str; params: dict; baseline_params: dict; diff_vs_baseline: dict
    strategy: BacktestResult; benchmark: BacktestResult
    stats: dict; bench_stats: dict                  # metrics.perf_stats (monthly)
    comparison: pd.DataFrame                        # rows: result_id, metric, paper, ours, diff, period, status, note
    checks: list[CheckResult]
    disclosures: list[str]                          # replication level, data, survivorship, coverage, gaps, assumptions, costs
    code: GeneratedCode
    replication_level: str                          # "L1" | "L2" | "L3"
alternative_universes(spec) -> list[dict]           # {key, label, feasible: bool, reason}
run(spec, universe_key: str | None = None, overrides: dict | None = None, cost_bps: float | None = None,
    n_trials: int = 1, kb: KB | None = None, paper_id: int | None = None) -> RunOutcome
```

Families and data:
- `cross_sectional_jk` → `us_equities_cached` (monthly) → `cross_sectional_jk`
- `time_series_momentum` → `commodity_futures_yahoo` (daily → monthly + EWMA vol) → `tsmom`
- `ml_market_timing` → Welch–Goyal → `engine.ml.kmz_timing`
- `unsupported` → refuse

Benchmark: `benchmark_equal_weight` on the same universe and costs (market buy-and-hold for ML timing).

Paper comparison:
- Like for like only: same variant, same metric, same gross/net, and over the paper's sample window where we have data.
- A `capm_alpha` comparison uses `kf_ff3` Mkt-RF and RF.
- If none of that applies, the row is "not comparable" with a reason. Never silently compared.
