SHELL := /bin/bash
PROJECT_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))

.PHONY: setup env verify test smoke backtest live-paper clean llm-smoke llm-report lint

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

live-paper:
	./scripts/run_live_paper.sh

clean:
	rm -rf .pytest_cache .mypy_cache
	find "$(PROJECT_ROOT)/results" -type f ! -name 'README.md' -delete

llm-smoke:
	./scripts/llm_smoke_test.sh

llm-report:
	python3 -m src.main llm-report

lint:
	python3 -m compileall src tests lean_workspace/QualityGrowthPi
