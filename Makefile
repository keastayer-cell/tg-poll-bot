.PHONY: setup test coverage lint format stage

setup:
	python3 -m venv venv
	venv/bin/python -m pip install -r requirements-dev.txt

test:
	venv/bin/pytest

coverage:
	venv/bin/pytest --cov=app.models --cov=app.storage --cov=app.votes --cov-report=term-missing --cov-fail-under=80

lint:
	venv/bin/ruff check app deploy tests
	venv/bin/ruff format --check app deploy tests

format:
	venv/bin/ruff format app deploy tests
	venv/bin/ruff check --fix app deploy tests

stage:
	./scripts/run_stage.sh
