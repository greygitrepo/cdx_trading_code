.PHONY: ci-local lint test report clean

ci-local: lint test report

lint:
	ruff check .

test:
	pytest -q

report:
	python bot/scripts/run_paper.py
	test -f reports/paper.html

clean:
	rm -rf .venv .pytest_cache .ruff_cache __pycache__ */__pycache__
