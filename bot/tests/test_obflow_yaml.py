from __future__ import annotations

from bot.configs.schemas import load_app_config
from bot.core.signals.obflow import OBFlowConfig


def test_obflow_config_from_yaml_defaults() -> None:
    app = load_app_config(path=__import__("pathlib").Path("bot/configs/config.yaml"))
    cfg = OBFlowConfig.from_params(app.params)
    assert cfg.depth_imb_L5_min == app.params.obflow.depth_imb_L5_min
    assert cfg.spread_tight_mult_mid == app.params.obflow.spread_tight_mult_mid
    assert cfg.c_absorption_min == app.params.obflow.c_absorption_min

