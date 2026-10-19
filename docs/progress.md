# Progress board

*Completed 2026-10-19. The product matches the plan in `docs/plan.md`.*

## Status by requirement

| Requirement (your brief) | Status | Evidence |
|---|---|---|
| Phase 0: audit | **done** | `docs/audit.md`; v0 suite 243/243 in an isolated copy; 6 critical, 7 high findings |
| Phase 1: research | **done** | `docs/research.md` |
| Phase 2: design | **done** | `docs/design.md` |
| 1. Paper upload | **done** | `app.py` → Library; PDFs hashed into the knowledge base |
| 2. Cited spec + assumptions approved | **done** | `replicator/extract`; Paper & spec approval; citation checks in `extract/citations.py` |
| 3. Readable strategy page | **done** | `extract/explain.py`; app → Strategy page |
| 4. Code from the approved spec only, traceable | **done** | deterministic templates; `# spec:` bindings; validator; approval gate on the Code, Results, and Variables tabs |
| 5. Strategy + benchmark, paper vs ours, gap reasons | **done** | `pipeline.run`; gap reasons in `replicator/gaps.py` |
| 6. Six checks with known-answer tests + cross-check | **done** | `checks/six.py`; 13 review findings fixed; metrics cross-checked against empyrical and statsmodels |
| 7. Variables tab, baseline kept, alternative universes | **done** | app → Variables; versioned runs |
| 8. Knowledge base, versioned | **done** | `kb/store.py` (SQLite + artifacts) |
| No look-ahead, with tests | **done** | point-in-time engine; truncation and perturbation tests on full strategies and generated code |
| Survivorship and limits disclosed on every result | **done** | disclosures panel always visible |
| ML: walk-forward, seeds, paper's split | **done** | `engine/ml.py`; combinatorial purged CV in `replicator/ml_cv.py` |
| Never fill gaps silently | **done** | `GapReport` everywhere; stricter after review (B4-04/09/10) |
| Golden set | **done** | `docs/golden-results.md`: KMZ replicates (L3); J&T Tier 1 passes (L1); 3 free-data rebuilds fall short, with the bias measured |
| Tests | **77 new + 224 old (fast) passing** | re-run by me after every agent |

## Timeline

| Time (HKT) | Milestone |
|---|---|
| 16:09 | Start. Deadline confirmed (23:59). Scope: everything, end to end |
| 16:14 | Design contract written; dependencies installed; Ken French data, MOP and KMZ PDFs downloaded |
| 16:15 | Wave 1 launched (5 agents) |
| 16:17–16:18 | 4 of 5 wave-1 agents done; 47 tests pass |
| 16:18 | Audit and research docs written; old suite verified in isolation (243 pass) |
| 16:20 | Engine review: 2 defects fixed (cohort netting, benchmark look-ahead) |
| 16:21 | Wave 2 launched (4 agents) + live J&T extraction test |
| 16:23–16:24 | Golden runs, app and blind review done; 13 review findings → fixer agent launched |
| 16:24–16:25 | KMZ replicates; service layer done |
| 16:27 | Fixer done: 77 tests pass; golden reports regenerated on the fixed code |
| 16:28 | TSMOM union-calendar defect found and fixed (golden + pipeline) |
| 16:30 | Approval gate added to the Code/Results/Variables tabs; new README; entry point switched to the new app |

## 2026-10-19 — complete

The product matches the plan. Start it with `.venv/bin/streamlit run app.py` and open http://localhost:8501. The walk-through is in `README.md`. Re-run the suite with `.venv/bin/python -m pytest tests/rp -q --tb=line`.
