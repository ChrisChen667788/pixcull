# v0.10-P2-A — convenience targets for the design-system uplift.
# Most engineering work runs through pip + pytest directly; this Makefile
# carries the tasks where typing the full python command is friction.

.PHONY: tokens tokens-check lint-design tests serve clean help

PYTHON ?= python

help:
	@echo "PixCull · convenience targets"
	@echo
	@echo "  make tokens         Compile design-system/tokens.json → CSS + Swift + Python"
	@echo "  make tokens-check   CI mode — verify on-disk outputs are in sync"
	@echo "  make lint-design    Lint inline hex colors against the baseline"
	@echo "  make tests          Full pytest sweep (except known-broken test_v1_1_scripts)"
	@echo "  make serve          Boot scripts/serve_demo.py on :8770"
	@echo "  make clean          Drop derived artefacts (__pycache__, .pytest_cache)"

tokens:
	$(PYTHON) scripts/build_design_tokens.py

tokens-check:
	$(PYTHON) scripts/build_design_tokens.py --check

lint-design:
	$(PYTHON) scripts/lint_design_tokens.py

tests:
	$(PYTHON) -m pytest tests/ --ignore=tests/test_v1_1_scripts.py

serve:
	PYTHONPATH=. $(PYTHON) scripts/serve_demo.py

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache
