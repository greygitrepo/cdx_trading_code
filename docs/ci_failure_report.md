# CI Failure Report

This document summarizes recent CI failures and tracks fixes to stabilize the pipeline.

Note: Generated without access to GitHub Actions logs from this environment. Please paste the run IDs and key log snippets below to complete the record. The fixes referenced are already applied in this branch and verified locally.

## Summary (fill in run IDs)

- Run ID: <paste>
  - Commit: <sha>
  - Failed step: ruff | pytest | run_paper | artifact
  - Root cause (one line): <one-liner>
  - Reproduce: `python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt && ruff check . && pytest -q && python bot/scripts/run_paper.py`
  - Log highlights (<=10 lines):
    ```text
    <paste relevant lines>
    ```

- Run ID: <paste>
  - Commit: <sha>
  - Failed step: ruff | pytest | run_paper | artifact
  - Root cause (one line): <one-liner>
  - Reproduce: <same as above>
  - Log highlights:
    ```text
    <paste>
    ```

- Run ID: <paste>
  - Commit: <sha>
  - Failed step: ruff | pytest | run_paper | artifact
  - Root cause (one line): <one-liner>
  - Reproduce: <same>
  - Log highlights:
    ```text
    <paste>
    ```

- Run ID: <paste>
  - Commit: <sha>
  - Failed step: ruff | pytest | run_paper | artifact
  - Root cause (one line): <one-liner>
  - Reproduce: <same>
  - Log highlights:
    ```text
    <paste>
    ```

## Fixes Applied

- Enforced stub-only execution for CI paths and verified no network is required:
  - REST stub layer (`bot/core/data_rest.py`) routes to `data/stubs/rest/*.json` when `STUB_MODE=true` (set in CI).
  - WS stub layer (`bot/core/data_ws.py`) replays `data/stubs/ws/*.jsonl` in stub mode.
  - Paper report (`bot/scripts/run_paper.py`) uses only local reporting code and writes `reports/paper.html` (no network).
- Robust env parsing and logging
  - Numeric env parsing made comment-resistant across modules.
  - Structured logging added to live runner; unrelated to CI, but improves diagnosability.
- CI doc and local runner added (see below) to reproduce pipeline locally.

## Local Reproduction (deterministic, no network)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

ruff check .
pytest -q
python bot/scripts/run_paper.py
test -f reports/paper.html
```

## Remaining Risks and Mitigations

- If any test imports live exchange clients and performs real HTTP calls, ensure `STUB_MODE=true` paths are used or monkeypatch network calls to pure fakes (see `tests/test_rest_api.py`).
- Headless environments: `run_paper.py` generates simple HTML (no GUI/fonts/plot libs) to avoid display dependencies.

