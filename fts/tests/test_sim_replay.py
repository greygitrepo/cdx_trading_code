import random

from fts.data.feeds import UnifiedFeed
from fts.exec.execution import execute_trade
from fts.signal.fts_signal import FTSConfig, evaluate_fts


def test_simulator_winrate():
    random.seed(0)
    cfg = FTSConfig()
    feed = UnifiedFeed(seed=0)
    wins = 0
    trades = 0
    for _ in range(40):
        event = next(feed)
        sig = evaluate_fts(event, cfg)
        if sig:
            pnl = execute_trade(event, sig)
            if pnl > 0:
                wins += 1
            trades += 1
    assert trades > 0 and wins / trades >= 0.7
