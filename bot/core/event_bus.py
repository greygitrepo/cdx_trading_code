import asyncio
from collections import defaultdict
from typing import AsyncIterator, Dict

class EventBus:
    """Simple symbol-keyed async event bus."""

    def __init__(self) -> None:
        self._queues: Dict[str, asyncio.Queue] = defaultdict(asyncio.Queue)

    async def publish(self, symbol: str, event: dict) -> None:
        """Publish an event for a symbol."""
        await self._queues[symbol].put(event)

    async def subscribe(self, symbol: str) -> AsyncIterator[dict]:
        q = self._queues[symbol]
        while True:
            evt = await q.get()
            yield evt
