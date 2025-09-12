from fts.signal.fts_signal import FTSConfig, evaluate_fts
from fts.common.types import Event


def test_signal_triggers():
    cfg = FTSConfig()
    event = Event(
        price=105,
        microprice=99,
        depth_ratio=0.3,
        z_flow=3.5,
        lambda_drop=0.3,
        anchor=100,
    )
    sig = evaluate_fts(event, cfg)
    assert sig is not None and sig.side == "SELL"


def test_signal_blocks():
    cfg = FTSConfig()
    event = Event(
        price=105,
        microprice=101,
        depth_ratio=0.6,
        z_flow=2.0,
        lambda_drop=0.6,
        anchor=100,
    )
    sig = evaluate_fts(event, cfg)
    assert sig is None
