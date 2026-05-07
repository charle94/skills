# Convenience targets for the credit-risk-strategy skill.
# Always run from the repo's `risk-control-credit-strategy/` directory.

PYTHON ?= python3
OUT ?= analysis_output

.PHONY: help test test-quick install base risk dynamic causal tuning vintage monitor full simulate clean

help:
	@echo "Targets:"
	@echo "  make test                        Run pytest suite"
	@echo "  make install                     Install runtime + test deps"
	@echo "  make base                        Run base_limit on examples/base_limit_sample.csv"
	@echo "  make risk                        Run risk_adjustment example"
	@echo "  make dynamic                     Run dynamic_adjustment example"
	@echo "  make causal                      Run causal_evaluation example"
	@echo "  make tuning                      Run strategy_tuning example"
	@echo "  make vintage                     Run vintage_analysis example"
	@echo "  make monitor BASE=<csv>          Run portfolio_monitoring (BASE required)"
	@echo "  make full                        Run full_limit_strategy example"
	@echo "  make simulate CHALLENGER=<json>  Run champion/challenger simulation"
	@echo "  make clean                       Remove $(OUT)/"

install:
	$(PYTHON) -m pip install -r requirements.txt

test:
	$(PYTHON) -m pytest tests/ -q

test-quick:
	$(PYTHON) -m pytest tests/ -q -x --ignore=tests/test_pipeline_integration.py

base:
	$(PYTHON) scripts/analysis_pipeline.py --input-path examples/base_limit_sample.csv --mode base_limit --output-dir $(OUT)/base

risk:
	$(PYTHON) scripts/analysis_pipeline.py --input-path examples/risk_adjustment_sample.csv --mode risk_adjustment --output-dir $(OUT)/risk

dynamic:
	$(PYTHON) scripts/analysis_pipeline.py --input-path examples/dynamic_adjustment_sample.csv --mode dynamic_adjustment --output-dir $(OUT)/dynamic

causal:
	$(PYTHON) scripts/analysis_pipeline.py --input-path examples/causal_evaluation_sample.csv --mode causal_evaluation --output-dir $(OUT)/causal

tuning:
	$(PYTHON) scripts/analysis_pipeline.py --input-path examples/strategy_tuning_sample.csv --mode strategy_tuning --output-dir $(OUT)/tuning

vintage:
	$(PYTHON) scripts/analysis_pipeline.py --input-path examples/vintage_analysis_sample.csv --mode vintage_analysis --output-dir $(OUT)/vintage

monitor:
	@if [ -z "$(BASE)" ]; then echo "BASE=<base_period.csv> required"; exit 1; fi
	$(PYTHON) scripts/analysis_pipeline.py --input-path examples/portfolio_monitoring_sample.csv --base-period-path $(BASE) --mode portfolio_monitoring --output-dir $(OUT)/monitor

full:
	$(PYTHON) scripts/analysis_pipeline.py --input-path examples/base_limit_sample.csv --mode full_limit_strategy --output-dir $(OUT)/full

simulate:
	@if [ -z "$(CHALLENGER)" ]; then echo "CHALLENGER=<challenger.json> required"; exit 1; fi
	$(PYTHON) scripts/analysis_pipeline.py --input-path examples/base_limit_sample.csv --mode simulation --challenger-config-path $(CHALLENGER) --output-dir $(OUT)/simulate

clean:
	rm -rf $(OUT)
