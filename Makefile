# v0.10-P2-A — convenience targets for the design-system uplift.
# Most engineering work runs through pip + pytest directly; this Makefile
# carries the tasks where typing the full python command is friction.

.PHONY: tokens tokens-check lint-design tests serve clean help \
        modelscope-dryrun modelscope-sync \
        goldenset goldenset-dryrun results-html

PYTHON ?= python

help:
	@echo "PixCull · convenience targets"
	@echo
	@echo "  make results-html   Rebuild templates/results.html from templates/src/ (edit src, never the artifact)"
	@echo "  make tokens         Compile design-system/tokens.json → CSS + Swift + Python"
	@echo "  make tokens-check   CI mode — verify on-disk outputs are in sync"
	@echo "  make lint-design    Lint inline hex colors against the baseline"
	@echo "  make tests          Full pytest sweep (except known-broken test_v1_1_scripts)"
	@echo "  make serve          Boot scripts/serve_demo.py on :8770"
	@echo "  make clean          Drop derived artefacts (__pycache__, .pytest_cache)"
	@echo
	@echo "  make modelscope-dryrun   Preview the rewritten README (no upload)"
	@echo "  make modelscope-sync     Push README to ModelScope (needs MODELSCOPE_API_TOKEN)"

results-html:
	$(PYTHON) scripts/build_results_html.py

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

# ModelScope README sync.  Use the venv that actually has the
# modelscope SDK installed (pixcull/.venv, ~3.7 GB with torch etc.;
# the lighter top-level .venv does not include it).
modelscope-dryrun:
	pixcull/.venv/bin/python scripts/sync_modelscope_readme.py --dry-run

modelscope-sync:
	pixcull/.venv/bin/python scripts/sync_modelscope_readme.py

# v0.11-P0-1 — Goldenset builder.  Aggregates every human-labeled
# source (out_wedding_eval/*/ground_truth.csv, ~/.pixcull/runs/*/
# annotations.jsonl, in-app rubric_human_labeled corrections) into
# goldenset/v0.11/ground_truth.csv ready for `train_rescorer.py`.
goldenset:
	$(PYTHON) scripts/build_goldenset.py

goldenset-dryrun:
	$(PYTHON) scripts/build_goldenset.py --dry-run
