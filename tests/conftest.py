import os
import pytest


def has_testnet_creds():
    # Keep requirements minimal to avoid false negatives in CI
    return (
        os.getenv("TESTNET", "false").lower() == "true"
        and os.getenv("BYBIT_API_KEY")
        and os.getenv("BYBIT_API_SECRET")
    )


def pytest_collection_modifyitems(config, items):
    is_ci = os.getenv("GITHUB_ACTIONS") == "true"
    for item in items:
        if "integration" in item.keywords or "ops" in item.keywords:
            if is_ci:
                item.add_marker(pytest.mark.skip(reason="Skip ops/integration in CI"))
            elif not has_testnet_creds():
                item.add_marker(
                    pytest.mark.skip(reason="No TESTNET creds/env for ops/integration")
                )
