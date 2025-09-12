from __future__ import annotations

import argparse
from pathlib import Path

from ..common.utils import load_yaml
from ..data.feeds import UnifiedFeed
from ..exec.execution import execute_trade
from ..report.ledger import TradeRecord
from ..report.report import write_report
from ..risk.risk import RiskManager
from ..signal.fts_signal import FTSConfig, evaluate_fts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--hours", type=int, default=1)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", type=str, default="fts_artifacts")
    args = parser.parse_args()

    cfg_dict = load_yaml(args.config)
    cfg = FTSConfig(**cfg_dict)
    feed = UnifiedFeed(seed=args.seed)
    risk = RiskManager()
    records = []
    steps = args.hours * 60
    for _ in range(steps):
        event = next(feed)
        sig = evaluate_fts(event, cfg)
        if sig:
            pnl = execute_trade(event, sig)
            if not risk.check(pnl):
                break
            records.append(TradeRecord(side=sig.side, entry=event.price, pnl=pnl))
    out_dir = Path(args.out)
    write_report(records, out_dir)


if __name__ == "__main__":
    main()
