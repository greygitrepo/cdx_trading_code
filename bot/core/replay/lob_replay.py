"""OB-Flow v2: Simple LOB replay from JSONL logs (skeleton)."""
from __future__ import annotations
from pathlib import Path
from typing import Tuple
import json

from bot.core.book import L2Book, process_stream


def replay_from_jsonl(path: Path, symbol: str) -> Tuple[L2Book, int]:
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s:
            continue
        try:
            ev = json.loads(s)
        except Exception:
            continue
        if isinstance(ev, dict) and ev.get("symbol") == symbol and ev.get("type") in {"snapshot", "delta"}:
            events.append(ev)
    book = L2Book(symbol=symbol)
    return process_stream(book, events)
