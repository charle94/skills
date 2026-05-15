# Convenience targets for the pi-credit-risk package.
# Always run from the package's `pi-credit-risk/` directory.

PYTHON ?= python3
RUN_ID ?= example
RUNS_DIR ?= runs

.PHONY: help install test test-quick example reproducibility clean

help:
	@echo "Targets:"
	@echo "  make install               Install pinned Python deps from requirements.txt"
	@echo "  make test                  Run full pytest suite"
	@echo "  make test-quick            Run unit tests (skip integration)"
	@echo "  make example               Run end-to-end pipeline on examples/ with RUN_ID=$(RUN_ID)"
	@echo "  make reproducibility       Run example twice and diff artifact hashes"
	@echo "  make clean                 Remove $(RUNS_DIR)/"

install:
	$(PYTHON) -m pip install -r requirements.txt

test:
	$(PYTHON) -m pytest tests/ -q

test-quick:
	$(PYTHON) -m pytest tests/ -q -x --ignore=tests/test_pipeline_integration.py

example:
	$(PYTHON) scripts/run_pipeline.py \
	  --config examples/run_config.example.json \
	  --output-dir $(RUNS_DIR)/$(RUN_ID) \
	  --stage all

reproducibility:
	@rm -rf $(RUNS_DIR)/_repro_a $(RUNS_DIR)/_repro_b
	$(PYTHON) scripts/run_pipeline.py --config examples/run_config.example.json --output-dir $(RUNS_DIR)/_repro_a --stage all
	$(PYTHON) scripts/run_pipeline.py --config examples/run_config.example.json --output-dir $(RUNS_DIR)/_repro_b --stage all
	$(PYTHON) -c "import json; a=json.load(open('$(RUNS_DIR)/_repro_a/manifest.json'))['artifacts']; b=json.load(open('$(RUNS_DIR)/_repro_b/manifest.json'))['artifacts']; diff=[k for k in a if a[k]!=b.get(k)]; print('OK: artifacts identical') if not diff else (print('FAIL: differing artifacts: %s' % diff) or exit(1))"

clean:
	rm -rf $(RUNS_DIR)
