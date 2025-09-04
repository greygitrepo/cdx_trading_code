"""Symbol selector: returns top-N candidates excluding managed/open symbols.

Pluggable scoring is out of scope; for now, selection assumes the input list
is already ranked and filters out excluded symbols.
"""

from __future__ import annotations

from typing import Iterable, List, Set


def top_n(candidates: Iterable[str], n: int, *, exclude_symbols: Set[str] | None = None) -> List[str]:
    exclude = exclude_symbols or set()
    out: list[str] = []
    for s in candidates:
        if s in exclude:
            continue
        out.append(s)
        if len(out) >= n:
            break
    return out
