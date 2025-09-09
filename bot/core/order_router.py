import asyncio
import inspect
from typing import Dict, NamedTuple, Optional

class ExecResult(NamedTuple):
    ok: bool
    order_id: Optional[str]
    status: str
    reason: Optional[str]

class OrderRouter:
    """Idempotent order sender with concurrency control."""

    def __init__(self, api, rate_sem: asyncio.Semaphore) -> None:
        self.api = api
        self.sem = rate_sem
        self._sent: Dict[str, ExecResult] = {}

    async def send(self, order: dict, idem_key: str, timeout_s: float = 2.0) -> ExecResult:
        if idem_key in self._sent:
            return self._sent[idem_key]
        async with self.sem:
            try:
                if inspect.iscoroutinefunction(self.api.place_order):
                    coro = self.api.place_order(order, client_order_id=idem_key)
                else:
                    coro = asyncio.to_thread(
                        self.api.place_order, order, client_order_id=idem_key
                    )
                resp = await asyncio.wait_for(coro, timeout=timeout_s)
                oid = resp.get("orderId") or resp.get("result", {}).get("orderId")
                status = resp.get("status") or resp.get("retMsg", "ok")
                res = ExecResult(True, oid, status, None)
            except asyncio.TimeoutError:
                res = ExecResult(False, None, "timeout", "timeout")
            except Exception as e:  # noqa: BLE001
                res = ExecResult(False, None, "error", str(e))
        self._sent[idem_key] = res
        return res
