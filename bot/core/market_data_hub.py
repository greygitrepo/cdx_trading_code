import logging
import time
from typing import Iterable

from .event_bus import EventBus

class MarketDataHub:
    """Fan-out incoming market data to symbol queues."""

    def __init__(self, source, bus: EventBus) -> None:
        self.source = source
        self.bus = bus
        self.logger = logging.getLogger(__name__)

    async def run(self, symbols: Iterable[str]) -> None:
        async for evt in self.source:
            sym = evt.get("symbol")
            if sym not in symbols:
                continue
            now = int(time.time() * 1000)
            ts = evt.get("ts", now)
            if now - ts > 200:
                evt["stale"] = True
            await self.bus.publish(sym, evt)
