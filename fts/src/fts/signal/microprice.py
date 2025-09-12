def microprice(bid: float, ask: float, bid_size: float, ask_size: float) -> float:
    return (ask * bid_size + bid * ask_size) / (bid_size + ask_size)
