.PHONY: install format format-check lint typecheck test coverage check run

install:
	uv sync --all-groups

format:
	uv run ruff format .

format-check:
	uv run ruff format --check .

lint:
	uv run ruff check .

typecheck:
	uv run basedpyright

test:
	uv run pytest -q

coverage:
	uv run pytest --cov=ashare_lab --cov-report=term-missing --cov-fail-under=90

check: format-check lint typecheck coverage

run:
	uv run uvicorn ashare_lab.main:app --host 127.0.0.1 --port 8000

