.PHONY: ci-local lint fmt test report clean quicktest replay

ci-local: lint test report

lint:
	ruff check .

fmt:
	ruff format .

test:
	pytest -q

report:
	python bot/scripts/run_paper.py
	test -f reports/paper.html

quicktest:
	python bot/scripts/run_quicktest.py

replay:
	python bot/scripts/run_replay_obflow.py

clean:
	rm -rf .venv .pytest_cache .ruff_cache __pycache__ */__pycache__
