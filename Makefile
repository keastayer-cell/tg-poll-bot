.PHONY: setup test lint format stage

setup:
	python3 -m venv venv
	venv/bin/python -m pip install -r requirements-dev.txt

test:
	venv/bin/pytest

lint:
	venv/bin/ruff check *.py deploy tests
	venv/bin/ruff format --check *.py deploy tests

format:
	venv/bin/ruff format *.py deploy tests
	venv/bin/ruff check --fix *.py deploy tests

stage:
	./run_stage.sh
