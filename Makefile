.PHONY: help install test coverage arch secrets smoke ruff ruff-bugs audit docs ci

# Prefer the project virtualenv when present.
PYTHON := $(shell if [ -x .venv/bin/python ]; then echo .venv/bin/python; else echo python3; fi)
PIP := $(PYTHON) -m pip

help:
	@echo "Common commands:"
	@echo "  make install   - Install package in editable mode (dev extras)"
	@echo "  make test      - Run pytest (skips IBKR/Telegram-credential tests)"
	@echo "  make coverage  - Generate coverage.xml + coverage badge"
	@echo "  make arch      - Enforce architecture boundary rules"
	@echo "  make secrets   - Scan git-tracked files for potential secrets"
	@echo "  make smoke     - Multi-market config + state isolation smoke test"
	@echo "  make ruff-bugs - Run Ruff bug-catching subset (matches CI gate)"
	@echo "  make ruff      - Run Ruff (may report pre-existing issues)"
	@echo "  make audit     - Run pip-audit dependency scan"
	@echo "  make docs      - Validate documentation path references"
	@echo "  make ci        - Run the same checks CI runs"

install:
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[dev]"

test:
	MPLBACKEND=Agg ./scripts/testing/run_tests.sh -m "not requires_ibkr and not requires_telegram"

coverage:
	MPLBACKEND=Agg $(PYTHON) -m pytest -m "not requires_ibkr and not requires_telegram" --cov=src/pearlalgo --cov-report=xml
	$(PYTHON) scripts/testing/generate_coverage_badge.py

arch:
	$(PYTHON) scripts/testing/check_architecture_boundaries.py --enforce

secrets:
	$(PYTHON) scripts/testing/check_no_secrets.py

smoke:
	$(PYTHON) scripts/testing/smoke_multi_market.py

ruff-bugs:
	$(PYTHON) -m ruff check src/pearlalgo --select F821,E722

ruff:
	$(PYTHON) -m ruff check .

audit:
	$(PYTHON) -m pip install --quiet --upgrade pip-audit
	$(PYTHON) -m pip_audit .

docs:
	$(PYTHON) scripts/testing/check_doc_references.py

ci: ruff-bugs arch secrets docs smoke audit test

