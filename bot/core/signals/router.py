"""OB-Flow v2: Single-strategy router."""
from __future__ import annotations

from typing import Optional, Dict, Any

from .obflow import decide, OBFlowConfig
from bot.core.book import L2Book


def route(book: L2Book, cfg: Optional[OBFlowConfig] = None) -> Optional[Dict[str, Any]]:
    return decide(book, cfg or OBFlowConfig())

