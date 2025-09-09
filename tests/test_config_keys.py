import warnings

from bot.devtools import audit_report


def test_unused_config_keys_warn_only():
    reports = audit_report.generate_reports(write=False)
    assert "unused_config_keys" in reports
    unused = reports["unused_config_keys"]
    if unused:
        warnings.warn(f"Unused config keys: {unused}")
