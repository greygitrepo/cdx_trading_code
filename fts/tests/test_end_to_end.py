import os
import subprocess
import sys
from pathlib import Path


def test_run_sim(tmp_path):
    config = Path("fts/config/runtime.yaml")
    out = tmp_path / "out"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "fts.runner.run_sim",
            "--config",
            str(config),
            "--hours",
            "1",
            "--seed",
            "1",
            "--out",
            str(out),
        ],
        check=True,
        env=env,
    )
    assert (out / "ledger.csv").exists()
