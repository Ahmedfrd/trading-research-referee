# Local check from the 2026-10-07 plan: lint, then the offline tests.
PY := .venv/bin/python
RUFF := .venv/bin/ruff

.PHONY: check lint test

check: lint test

lint:
	$(RUFF) check replicator tests/rp

test:
	$(PY) -m pytest tests/rp -q --tb=line -m "not network and not llm and not golden"
