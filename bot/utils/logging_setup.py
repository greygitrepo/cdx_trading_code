"""Minimal logging helpers for consistent handlers across scripts."""

from __future__ import annotations

import logging
from pathlib import Path


def get_logger(name: str = "app", level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(level)
    if not logger.handlers:
        sh = logging.StreamHandler()
        sh.setLevel(level)
        fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        sh.setFormatter(fmt)
        logger.addHandler(sh)
    return logger


def ensure_dir(p: str | Path) -> Path:
    d = Path(p)
    d.mkdir(parents=True, exist_ok=True)
    return d
