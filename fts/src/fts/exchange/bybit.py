import os


class BybitClient:
    """Minimal placeholder for Bybit client."""

    def __init__(self) -> None:
        self.api_key = os.getenv("BYBIT_API_KEY")
        self.api_secret = os.getenv("BYBIT_API_SECRET")
        if not self.api_key or not self.api_secret:
            self.available = False
        else:
            self.available = True
