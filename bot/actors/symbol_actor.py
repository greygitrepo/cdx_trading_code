import time
from bot.core.event_bus import EventBus
from bot.core.order_router import OrderRouter
from bot.core.risk_math import tp_sl_trigger, will_enter

class SymbolActor:
    def __init__(self, symbol: str, cfg: dict, bus: EventBus, router: OrderRouter, clock=time.time):
        self.symbol = symbol
        self.cfg = cfg
        self.bus = bus
        self.router = router
        self.clock = clock
        self.state = "IDLE"
        self.pos = None
        self.last_md = None

    async def run(self) -> None:
        async for evt in self.bus.subscribe(self.symbol):
            self.last_md = evt
            await self.step()

    async def step(self) -> None:
        now_ms = int(self.clock() * 1000)
        if self.state in ("IDLE", "EVAL"):
            if (
                self.last_md
                and not self.last_md.get("stale")
                and will_enter(self.last_md, self.cfg)
            ):
                self.state = "ENTER_PENDING"
                idem = f"{self.symbol}-{now_ms}-enter"
                res = await self.router.send(order=self._build_entry(), idem_key=idem)
                if res.ok:
                    self.state = "ENTERED"
                    self.pos = {
                        "entry_px": self.last_md["payload"]["mid"],
                        "qty": self.cfg["risk"]["qty"],
                    }
                else:
                    self.state = "EVAL"
        elif self.state == "ENTERED":
            trig = tp_sl_trigger(self.pos, self.last_md, self.cfg)
            if trig["should_exit"]:
                self.state = "EXIT_PENDING"
                idem = f"{self.symbol}-{now_ms}-exit"
                res = await self.router.send(order=self._build_exit(), idem_key=idem)
                self.state = "EXITED" if res.ok else "ENTERED"

    def _build_entry(self) -> dict:
        return {"symbol": self.symbol, "side": "Buy", "qty": self.cfg["risk"]["qty"]}

    def _build_exit(self) -> dict:
        return {"symbol": self.symbol, "side": "Sell", "qty": self.cfg["risk"]["qty"]}
