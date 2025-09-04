import os
import pytest


def has_testnet_creds():
    return (
        os.getenv("TESTNET", "false").lower() == "true"
        and os.getenv("LIVE_MODE", "false").lower() == "true"
        and os.getenv("STUB_MODE", "true").lower() == "false"
        and os.getenv("PAPER_MODE", "true").lower() == "false"
        and os.getenv("BYBIT_API_KEY")
        and os.getenv("BYBIT_API_SECRET")
    )


def pytest_collection_modifyitems(config, items):
    for item in items:
        if ("integration" in item.keywords or "ops" in item.keywords) and not has_testnet_creds():
            item.add_marker(pytest.mark.skip(reason="No TESTNET creds/env for integration/ops"))
