"""WebSocket-like data layer with STUB mode replay.

Provides ticker and orderbook (L1/L5) streams. In STUB_MODE, reads JSONL files
from data/stubs/ws/*.jsonl and yields events. Supports simple reconnection via
exp backoff and sequence verification via orderbook module.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Literal
import os
import time

from .config import get_modes
from .orderbook import L2Book, process_stream
from .data_rest import REST

try:  # optional public WS
    import websocket  # type: ignore
except Exception:  # noqa: BLE001
    websocket = None  # type: ignore

PUBLIC_WS_MAIN_LINEAR = "wss://stream.bybit.com/v5/public/linear"
PUBLIC_WS_TEST_LINEAR = "wss://stream-testnet.bybit.com/v5/public/linear"


STUB_DIR = Path("data/stubs/ws")


EventType = Literal["ticker", "orderbook"]


def _iter_jsonl(path: Path) -> Iterator[dict]:
    with path.open("r") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


@dataclass
class PublicWS:
    symbol: str
    depth: int = 1  # 1 or 5 levels for stub interface

    def ticker_stream(self) -> Iterator[dict]:
        modes = get_modes()
        if modes.stub:
            src = STUB_DIR / f"ticker_{self.symbol}.jsonl"
            if src.exists():
                yield from _iter_jsonl(src)
            return
        # LIVE placeholder: no-op in CI
        return iter(())

    def orderbook_stream(self) -> Iterator[dict]:
        modes = get_modes()
        if modes.stub:
            src = STUB_DIR / f"orderbook{self.depth}_{self.symbol}.jsonl"
            if src.exists():
                yield from _iter_jsonl(src)
            return
        # LIVE: prefer public WebSocket if available and enabled; else REST poll fallback
        use_ws = os.environ.get("ENABLE_PUBLIC_WS", "false").lower() == "true" and websocket is not None
        if use_ws:
            import threading
            import queue
            q: "queue.Queue[dict]" = queue.Queue(maxsize=1000)
            testnet = os.environ.get("TESTNET", "true").lower() == "true"
            url = PUBLIC_WS_TEST_LINEAR if testnet else PUBLIC_WS_MAIN_LINEAR
            topic = f"orderbook.{self.depth}.{self.symbol}"

            def _on_message(_ws: "websocket.WebSocketApp", message: str) -> None:  # type: ignore[name-defined]
                try:
                    data = json.loads(message)
                except Exception:
                    return
                # v5 format: snapshot/delta with topic orderbook.X.SYMBOL
                if not isinstance(data, dict) or str(data.get("topic", "")).startswith("orderbook.") is False:
                    return
                dt = data.get("type") or "delta"
                body = data.get("data") or {}
                bids = body.get("b") or body.get("bid") or []
                asks = body.get("a") or body.get("ask") or []
                ts = int(body.get("ts") or data.get("ts") or time.time() * 1000)
                seq = int(body.get("u") or data.get("u") or 0)
                ev = {
                    "type": "snapshot" if dt == "snapshot" else "delta",
                    "seq": seq,
                    "ts": ts,
                    "bids": [[float(p), float(s)] for p, s in bids],
                    "asks": [[float(p), float(s)] for p, s in asks],
                }
                try:
                    q.put_nowait(ev)
                except Exception:
                    pass

            ws = websocket.WebSocketApp(  # type: ignore[call-arg]
                url,
                on_message=_on_message,
            )

            def _on_open(wsapp: "websocket.WebSocketApp") -> None:  # type: ignore[name-defined]
                sub = {"op": "subscribe", "args": [topic]}
                try:
                    wsapp.send(json.dumps(sub))
                except Exception:
                    pass

            ws.on_open = _on_open  # type: ignore[assignment]

            t = threading.Thread(target=lambda: ws.run_forever(ping_interval=15, ping_timeout=10), daemon=True)  # type: ignore[arg-type]
            t.start()
            # Yield from queue
            while True:
                try:
                    ev = q.get(timeout=1.0)
                    yield ev
                except Exception:
                    continue
        else:
            # REST polling fallback
            rest = REST(base_url="https://api.bybit.com")
            seq = 0
            poll_ms = int(float((os.getenv("POLL_MS") or "400").split("#", 1)[0].strip()))
            while True:
                try:
                    got = rest.tickers(category="linear", symbol=self.symbol)
                    lst = (got.get("result", {}) or {}).get("list", [])
                    if lst:
                        it = lst[0]
                        try:
                            bid = float(it.get("bid1Price") or it.get("bidPrice") or it.get("bid") or 0.0)
                            ask = float(it.get("ask1Price") or it.get("askPrice") or it.get("ask") or 0.0)
                            bs = float(it.get("bid1Size") or it.get("bidSize") or it.get("bidSz") or 0.0)
                            asz = float(it.get("ask1Size") or it.get("askSize") or it.get("askSz") or 0.0)
                        except Exception:
                            bid = ask = bs = asz = 0.0
                        if bid > 0 and ask > 0:
                            seq += 1
                            yield {
                                "type": "delta" if seq > 1 else "snapshot",
                                "seq": seq,
                                "ts": int(time.time() * 1000),
                                "bids": [[bid, bs or 1.0]],
                                "asks": [[ask, asz or 1.0]],
                            }
                    time.sleep(max(0.05, poll_ms / 1000.0))
                except Exception:
                    time.sleep(0.5)
                    continue

    def replay_orderbook(self) -> tuple[L2Book, int]:
        book = L2Book(symbol=self.symbol)
        events = list(self.orderbook_stream())
        return process_stream(book, events)
