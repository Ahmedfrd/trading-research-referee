# Replicator

Replicator reads a trading-strategy paper and walks you from the PDF to a finished run. It stores the paper, extracts a cited specification, asks you to approve every assumption, fills a code template from that specification, and runs the strategy beside a benchmark. The Results tab puts the paper's reported numbers next to the numbers from this run, with the six checks, gap reasons, disclosures, and a manifest.

## Run

From the repository root:

```bash
.venv/bin/streamlit run app.py
```

Open http://localhost:8501.

Re-run the offline suite with:

```bash
.venv/bin/python -m pytest tests/rp -q --tb=line
```

Extraction calls the Claude Code CLI (`claude`) with the model you pick in the sidebar. Each call is cached under `data/kb/llm_cache/` and appended to `reports/llm_usage.jsonl`. The Supervisor tab reads that log.

## From launch to a finished run

The sidebar caption is the path: Library, then Paper & spec, then Review queue, then Code, then Results. Thorough extraction is the default. Single analyst is the shorter path.

### Library

On the Library tab, choose a PDF and click **Add to library**. The app reads the PDF, stores a copy, and records the paper in the knowledge base by file hash. The sidebar then lists it as `id: title`. Select that paper. Until a paper is selected, the other tabs wait.

### Thorough extraction

Leave **Extraction** on **Thorough**. On Paper & spec, click **Run thorough extraction**.

The run proceeds in this order. Finished steps are stored on the paper, so a later click reuses them.

1. **Analyst A** reads the paper into a specification (`prompts/v2/extract_spec.md`). Each field is `stated`, `derived`, `assumed`, or `unknown`, with a page and a verbatim quote on stated and derived fields. The specification lists strategy variants and reported results (table, row, column, page).
2. **Analyst B** reads the same paper on its own (`prompts/v2/analyst_b.md`). It does not see Analyst A's specification.
3. **Citation checks** are code. A quote has to sit on the cited page, and a number has to appear in that quote at the printed precision.
4. A field-level diff compares the two specifications. The **spec reviewer** (`prompts/v2/spec_reviewer.md`) sees each disagreement with the cited pages, in batches of 25 and at most four calls. It may settle a disagreement only when the quote check passes: the quote is on the cited page, it contains the chosen value, and it does not contain the rejected value. Sample dates, the chosen variant, universe fields, a result's metric, gross-or-net, and raw-versus-alpha label, and any assumed or unknown field, stay open for you.
5. The **reviser** (`prompts/v2/reviser.md`) gets at most two rounds, and only for a citation check that is still open. A patch is applied when its quote is on the cited page and contains the value.
6. The merged specification is saved. Auto-settled fields and open items are written to the Review queue.
7. The **supervisor** (`prompts/v2/supervisor.md`) makes one read-only pass. It adds notes for you. The specification stays as saved.

The page then shows the family, the chosen variant, and a table of every field: value, status, citations, and the citation-check verdict. Reported results are listed underneath, with a flag when a row belongs to a variant other than the chosen one. An expander shows the raw JSON.

### Review queue

Open the Review queue. It lists disagreements, citation checks that remain, and supervisor notes.

- **Use analyst A** or **Use analyst B** writes that reading into a new specification version.
- **Reject** leaves Analyst A's value in place and closes the item.
- **Or set a different value**, then **Save value**, writes the value you typed.
- A supervisor note has **Dismiss**.
- An auto-settled field shows the reviewer's choice and quote. **Undo settlement** swaps in the other analyst's value and marks the item reversed.

Code, Results, and Variables open once the queue has no open items and every assumed or unknown field is approved.

### Approve the specification

Back on Paper & spec, the Assumptions section lists every assumed or unknown field. Edit the value if you want, tick **Approve** on each one, and click **Approve spec**. That saves a new specification version. The first approved version is the baseline. The sidebar **Spec version** menu selects which version the other tabs use.

### Code

Open the Code tab. The source is filled from a template for the specification's family (`cross_sectional_jk`, `time_series_momentum`, `ml_market_timing`, or `factor_sort_2x3`). Every constant is tagged `# spec: <path>`. The tab shows the source, a binding table (constant, spec path, value, status), and the template check: each binding is used, and `run()` has no unbound number. Under that, it lists the checks that run with the strategy.

### Results

On Results, choose a universe and a one-way cost in basis points. The cost starts from the specification. Click **Run**.

The page then shows:

- the replication level, the family, and the universe
- a Disclosures panel for this run
- **Paper vs ours**: result id, metric, the paper's number, ours, the difference, the period, and a status. The comparison uses the chosen variant, the same metric, gross or net as reported, raw return or CAPM alpha as reported, and the paper's sample window. The pass rule is the replication check: the gap is within two combined standard errors, the sign matches, and significance at 5% matches
- **Likely reasons for any gap**, computed from this run's data and the specification
- a growth-of-1 chart of the strategy and the benchmark
- strategy stats and benchmark stats
- the six checks, each in its own expander: look-ahead, replication, transaction costs, significance, out-of-sample, and parameter sensitivity. A check shows its status (`pass`, `fail`, `warn`, or `n/a`), the method, the details, and a cross-check when one was recorded

For a price-panel family the benchmark is equal-weight over the same returns. For the market-timing family the benchmark is buy-and-hold of the market series used in the run.

The run writes a manifest. The page names the run id. Click **Draft gap note** to ask for a short paragraph (`prompts/v2/results_analyst.md`). The paragraph appears when every figure in it is already in the comparison or the gap table.

### Single analyst

Set **Extraction** to **Single analyst**. On Paper & spec, click **Run single-analyst extraction**. Analyst A runs once and the specification is saved. There is no second analyst, reviewer, reviser, or supervisor pass, and the Review queue stays empty from that run. Approve the assumptions, then use Code and Results as above.

## Sidebar

- **Paper** selects the stored paper. **Spec version** appears once a specification exists. The latest version is selected; the baseline is marked.
- **Model** is `sonnet`, `opus`, or `haiku`. **Model per role** sets the model for Analyst A, Analyst B, Spec reviewer, Reviser, Supervisor, Strategy page, Fact-checker, and Results note. A new session starts each role on the model selected above.
- **Extraction** is Thorough or Single analyst.
- **What a thorough run does** restates the two-analyst path.

## Tabs

| Tab | What you see |
|---|---|
| Library | The PDF uploader and **Add to library**. Tables of papers, specification versions, runs, and notes. A note box and **Add note**. |
| Paper & spec | The extraction button for the sidebar mode, the field table with citation checks, reported results, raw JSON, and the assumption approval form. |
| Strategy page | **Generate strategy page** writes the page (`prompts/v2/strategy_page.md`) and stores it on the specification. Sections, in order: Core idea, Intuition, Mechanics, The authors' arguments, Results, Limitations. Paper sentences carry page chips. A referee note is shown apart from the paper's sentences. In Thorough mode the fact-checker (`prompts/v2/fact_checker.md`) adds a line under each paper sentence on whether the quote supports it. |
| Code | The generated template, bindings, template check, and the list of checks that run with the strategy. Shown after the queue is settled and the specification is approved. |
| Results | Universe, cost, **Run**, then paper versus ours, gap reasons, the chart, stats, the six checks, disclosures, and **Draft gap note**. |
| Variables | The baseline value of each parameter and execution field is locked. Edit a value, choose a universe and a cost, and click **Re-run with overrides**. The page shows the diff against the baseline, then the same results view. Each variant counts toward the multiple-testing bar. A table lists runs for this paper. |
| Golden set | Stored reports for `jt`, `tsmom`, `umd`, and `kmz`. Each shows the replication level, the comparison table, disclosures, notes, and the raw JSON. The tables are written up in [docs/golden-results.md](docs/golden-results.md). |
| Supervisor | Supervisor notes from a thorough extraction, with severity and path. The agent trace lists each step with tokens in, tokens out, seconds, and time. The token log groups `reports/llm_usage.jsonl` by role. |
| Review queue | Open disagreements, citation checks, supervisor notes, and auto-settled fields, with the buttons described above. |

## Where files are written

Paths are relative to the repository root (`replicator/config.py`).

| Path | Contents |
|---|---|
| `data/papers/` | The uploaded PDF, under its original file name |
| `data/kb/kb.sqlite` | Knowledge base: papers, specification versions, code, runs, pages, notes, review items, agent trace |
| `data/kb/papers/<sha256>.pdf` | The stored copy of the PDF |
| `data/kb/llm_cache/` | Cached model responses |
| `data/kb/runs/<id>/` | Run artifacts (`returns`, `gross`, `benchmark`, `weights_tail` as Parquet) and `manifest.json` |
| `reports/exports/run-<id>/` | The same run folder, plus `spec.json` and `strategy.py` |
| `reports/llm_usage.jsonl` | One JSON line per model call: role, tokens, duration |
| `reports/golden/jt.json` | Jegadeesh and Titman golden report |
| `reports/golden/tsmom.json` | Moskowitz, Ooi and Pedersen golden report |
| `reports/golden/umd.json` | UMD golden report |
| `reports/golden/kmz.json` | Kelly, Malamud and Zhou golden report |
| `data/reference/` | Reference series used by the golden reports and the pipeline |
| `data/cache/prices/` | Cached price panels |
| `prompts/v2/` | Role prompts |

The manifest (`replicator.run_manifest.v1`) records the PDF hash, the specification, the generated-code digest, data provenance, library versions, and the check and gap summaries for that run.

## Documents

| Doc | Contents |
|---|---|
| [docs/plan.md](docs/plan.md) | The plan: phases, research, and the agent hierarchy |
| [docs/design.md](docs/design.md) | Interface contract for the package |
| [docs/research.md](docs/research.md) | Tools, data sources, and the architecture |
| [docs/audit.md](docs/audit.md) | Audit of the earlier tool |
| [docs/golden-results.md](docs/golden-results.md) | Golden-set tables |
| [docs/agent-evaluation.md](docs/agent-evaluation.md) | Offline checks of the agent path |
| [docs/agent-report.md](docs/agent-report.md) | Build log |
| [docs/progress.md](docs/progress.md) | Requirement status |
| [docs/review-wave1.md](docs/review-wave1.md) | Review notes from the build |

## Layout

```
app.py            entry point (streamlit run app.py)
replicator/       data, engine, checks, spec, ingest, extract, codegen, agents, kb, pipeline, golden, ui
prompts/v2/       role prompts
tests/rp/         offline tests
reports/golden/   golden reports
reports/exports/  per-run export folders
```
