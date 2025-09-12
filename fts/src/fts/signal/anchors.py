from typing import Dict


def compute_round_anchors(price: float) -> Dict[str, float]:
    return {
        "round_500": round(price / 500) * 500,
        "round_1000": round(price / 1000) * 1000,
    }
