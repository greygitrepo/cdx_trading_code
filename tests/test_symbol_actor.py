import asyncio
import time
from bot.core.event_bus import EventBus
from bot.core.order_router import ExecResult
from bot.actors.symbol_actor import SymbolActor


class DummyRouter:
    def __init__(self):
        self.calls = []

    async def send(self, order, idem_key, timeout_s: float = 2.0) -> ExecResult:
        self.calls.append(idem_key)
        return ExecResult(True, "1", "ok", None)


def test_actor_state_flow():
    bus = EventBus()
    router = DummyRouter()
    cfg = {"risk": {"qty": 1, "tp_pct": 0.05, "sl_pct": 0.05}, "min_edge": 0}
    actor = SymbolActor("BTCUSDT", cfg, bus, router, clock=time.time)

    async def _run():
        task = asyncio.create_task(actor.run())
        await bus.publish(
            "BTCUSDT",
            {"ts": int(time.time() * 1000), "type": "orderbook", "payload": {"mid": 100, "edge": 1}},
        )
        await asyncio.sleep(0.01)
        assert actor.state in {"ENTER_PENDING", "ENTERED"}
        await bus.publish(
            "BTCUSDT",
            {"ts": int(time.time() * 1000), "type": "orderbook", "payload": {"mid": 106}},
        )
        await asyncio.sleep(0.01)
        assert actor.state == "EXITED"
        task.cancel()

    asyncio.run(_run())


def test_stale_event_prevents_entry():
    bus = EventBus()
    router = DummyRouter()
    cfg = {"risk": {"qty": 1}, "min_edge": 0}
    actor = SymbolActor("BTCUSDT", cfg, bus, router, clock=time.time)

    async def _run():
        task = asyncio.create_task(actor.run())
        old_ts = int(time.time() * 1000) - 500
        await bus.publish(
            "BTCUSDT",
            {"ts": old_ts, "type": "orderbook", "payload": {"mid": 100}, "stale": True},
        )
        await asyncio.sleep(0.01)
        assert actor.state == "IDLE"
        task.cancel()

    asyncio.run(_run())
