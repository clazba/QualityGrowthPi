SHELL := /bin/bash
PROJECT_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))

.PHONY: setup env verify test smoke backtest workflow live-paper paper-check paper-status paper-stop paper-liquidate e2e baseline clean llm-smoke llm-report lint

setup:
	./scripts/bootstrap_pi.sh

env:
	./scripts/setup_env.sh

verify:
	./scripts/verify_install.sh

test:
	./scripts/run_tests.sh

smoke:
	./scripts/smoke_test.sh

backtest:
	./scripts/run_backtest.sh

workflow:
	./scripts/run_trade_workflow.sh

live-paper:
	./scripts/run_live_paper.sh

paper-check:
	./scripts/check_alpaca_paper.sh

paper-status:
	./scripts/paper_status.sh

paper-stop:
	./scripts/stop_live_paper.sh

paper-liquidate:
	./scripts/stop_live_paper.sh --liquidate

e2e:
	./scripts/run_e2e.sh

baseline:
ifndef BACKTEST_ID
	$(error BACKTEST_ID is required, e.g. make baseline BACKTEST_ID=<backtest_id>)
endif
	./scripts/capture_cloud_baseline.sh "$(BACKTEST_ID)"

clean:
	rm -rf .pytest_cache .mypy_cache
	find "$(PROJECT_ROOT)/results" -type f ! -name 'README.md' -delete

llm-smoke:
	./scripts/llm_smoke_test.sh

llm-report:
	./scripts/llm_report.sh

lint:
	python3 -m compileall src tests lean_workspace/QualityGrowthPi
