import asyncio
from bot.core.order_router import OrderRouter


class DummyAPI:
    def __init__(self, delay: float = 0.0):
        self.delay = delay
        self.calls = 0
        self.in_flight = 0
        self.max_in_flight = 0

    async def place_order(self, order, client_order_id=None):
        self.calls += 1
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        await asyncio.sleep(self.delay)
        self.in_flight -= 1
        return {"orderId": "1", "status": "ok"}


def test_timeout():
    api = DummyAPI(delay=0.2)
    router = OrderRouter(api, asyncio.Semaphore(1))

    async def _run():
        return await router.send({}, "a", timeout_s=0.05)

    res = asyncio.run(_run())
    assert not res.ok and res.status == "timeout"


def test_idempotency():
    api = DummyAPI()
    router = OrderRouter(api, asyncio.Semaphore(1))

    async def _run():
        r1 = await router.send({}, "same")
        r2 = await router.send({}, "same")
        return r1, r2

    res1, res2 = asyncio.run(_run())
    assert api.calls == 1
    assert res1 == res2


def test_rate_limit():
    api = DummyAPI(delay=0.05)
    router = OrderRouter(api, asyncio.Semaphore(1))

    async def _run():
        await asyncio.gather(router.send({}, "a"), router.send({}, "b"))

    asyncio.run(_run())
    assert api.max_in_flight == 1
    assert api.calls == 2
