"""Helpers and facade for live testnet runner.

This module exposes small utilities used by `bot/scripts/run_live_testnet.py`
to keep that script slim while preserving its behavior.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path as _P
from typing import Any
import time

from bot.utils.structlog import init_run_dir
from bot.app.runners.live_runner import LiveRunner


class LiveTestnetOrchestrator:
    """Orchestrates non-network side-effects for the live testnet runner.

    Provides small, testable helpers to keep the script slim without changing
    the behavior or external outputs.
    """

    @staticmethod
    def apply_strategy_overrides(app_cfg: Any, cli_name: str | None, cli_params: list[str] | None) -> None:
        name = (cli_name or "").strip()
        if name:
            try:
                app_cfg.strategy.name = name
            except Exception:
                pass
        sp: dict[str, str] = {}
        for item in (cli_params or []):
            if not item or "=" not in item:
                continue
            k, v = item.split("=", 1)
            sp[k.strip()] = v.strip()
        try:
            merged = dict(getattr(app_cfg.strategy, "params", {}) or {})
            merged.update(sp)
            app_cfg.strategy.params = merged
        except Exception:
            pass

    @staticmethod
    def emit_strategy_header(app_cfg: Any, logs_dir: _P, run_id: str) -> None:
        try:
            header = LiveRunner.build_header(app_ctx=None, config=app_cfg)
            write_event(
                logs_dir,
                {
                    "ts": int(time.time() * 1000),
                    "run_id": run_id,
                    "step": "run_header",
                    "strategy_name": header.strategy_name,
                    "strategy_cfg_hash": header.strategy_cfg_hash,
                    "strategy_params": header.params,
                },
            )
        except Exception:
            pass

    @staticmethod
    def export_resolved_from_yaml(runtime: Any, logger: logging.Logger, slog: Any) -> None:
        resolved: dict[str, str | float | int | bool] = {}
        warnings: list[dict] = []
        try:
            ee = runtime.params.entry_exit
            ob = runtime.params.orderbook
            fu = runtime.params.funding_time
            ex = runtime.app.exchange
            uv = runtime.params.universe
            mapping: list[tuple[str, object]] = [
                ("TP_PCT", ee.tp1),
                ("SL_PCT", ee.sl),
                ("TRAIL_AFTER_TP1_PCT", ee.trail_after_tp1),
                ("MIN_DEPTH_USD", ob.min_depth_usd),
                ("AVOID_TAKER_WITHIN_MIN", fu.avoid_taker_within_min),
                ("PREFER_LIMIT_DEFAULT", bool(ex.maker_post_only)),
                ("DYNAMIC_TAKER_ON_STRONG", bool(ex.taker_on_strong_score)),
                ("FALLBACK_IOC", bool(ex.fallback_ioc)),
                ("UNIVERSE_TOP_N", uv.topN),
                ("BYBIT_CATEGORY", ex.category),
                ("TESTNET", "true" if str(getattr(ex, "network", "testnet")).lower() == "testnet" else "false"),
            ]
            for key, yval in mapping:
                ystr = str(yval).lower() if isinstance(yval, bool) else str(yval)
                prev = os.environ.get(key)
                if prev is not None and prev != ystr:
                    warnings.append({"key": key, "env": prev, "yaml": ystr})
                os.environ[key] = ystr
                resolved[key] = yval
        except Exception as e:  # noqa: BLE001
            logger.warning(f"config:resolved export failed: {e}")
        if warnings:
            logger.warning(f"config:resolved conflicts: {warnings}")
            try:
                for w in warnings:
                    slog.log_info(ts=int(time.time() * 1000), symbol=None, tag="config:conflict", payload=w)  # type: ignore[arg-type]
            except Exception:
                pass
        try:
            slog.log_info(ts=int(time.time() * 1000), symbol=None, tag="config:resolved", payload=resolved)  # type: ignore[arg-type]
        except Exception:
            logger.info(f"config:resolved {resolved}")

    @staticmethod
    def apply_profile_overlay(runtime: Any, profile: str, logger: logging.Logger) -> bool:
        import yaml  # local import to avoid hard dep at module import time

        prof_name = "quick_test" if profile == "quick-test" else profile
        prof_path = _P(f"bot/configs/profiles/{prof_name}.yaml")
        if not prof_path.exists():
            return False
        with prof_path.open("r", encoding="utf-8") as f:
            overlay = yaml.safe_load(f) or {}
        def _merge_obj(obj, ov):
            for k, v in (ov or {}).items():
                if hasattr(obj, k) and not isinstance(v, dict):
                    setattr(obj, k, v)
                elif hasattr(obj, k) and isinstance(v, dict):
                    _merge_obj(getattr(obj, k), v)
        if overlay.get("exchange"):
            _merge_obj(runtime.app.exchange, overlay.get("exchange"))
        if overlay.get("risk"):
            _merge_obj(runtime.app.risk, overlay.get("risk"))
        if overlay.get("params"):
            _merge_obj(runtime.params, overlay.get("params"))
        if overlay.get("runtime"):
            _merge_obj(runtime.app.runtime, overlay.get("runtime"))
        logger.info(f"Applied profile overlay: {profile}")
        return True


def setup_loggers(run_id: str) -> tuple[logging.Logger, _P]:
    base_logs = _P("logs")
    base_logs.mkdir(parents=True, exist_ok=True)
    logs_dir = init_run_dir(base_logs, run_id)
    logs_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("live_testnet")
    logger.setLevel(logging.INFO)
    fh = logging.FileHandler(logs_dir / "app.log")
    fh.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    fh.setFormatter(fmt)
    if not logger.handlers:
        logger.addHandler(fh)
        sh = logging.StreamHandler(sys.stdout)
        sh.setLevel(logging.INFO)
        sh.setFormatter(fmt)
        logger.addHandler(sh)
    return logger, logs_dir


def write_event(logs_dir: _P, event: dict[str, Any]) -> None:
    fp = logs_dir / "events.jsonl"
    with fp.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def require_env_flags(logger: logging.Logger) -> None:
    flags = {
        "STUB_MODE": os.environ.get("STUB_MODE", "false").lower(),
        "PAPER_MODE": os.environ.get("PAPER_MODE", "false").lower(),
        "LIVE_MODE": os.environ.get("LIVE_MODE", "true").lower(),
        "TESTNET": os.environ.get("TESTNET", "true").lower(),
    }
    logger.info(f"Env flags: {flags}")


def load_dotenv_if_present() -> int:
    """Load key=value pairs from repo-root `.env` if present.

    Does not override already-set env vars. Returns number of variables loaded.
    """
    try:
        env_fp = _P(__file__).resolve().parents[3] / ".env"
    except Exception:
        return 0
    if not env_fp.exists():
        return 0
    loaded = 0
    for line in env_fp.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        k = k.strip()
        v = v.strip()
        if "#" in v:
            v = v.split("#", 1)[0].strip()
        if k and (k not in os.environ):
            os.environ[k] = v
            loaded += 1
    return loaded
