setup:
	pip install -r requirements.txt

lint:
	ruff src tests

test:
	pytest -q

sim:
	python -m fts.runner.run_sim --config config/runtime.yaml --hours 1 --seed 42
