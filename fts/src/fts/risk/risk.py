class RiskManager:
    def __init__(self, daily_cap: float = -0.025):
        self.daily_cap = daily_cap
        self.total_pnl = 0.0

    def check(self, pnl: float) -> bool:
        self.total_pnl += pnl
        return self.total_pnl > self.daily_cap
