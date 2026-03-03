from decimal import Decimal


class TradingMetrics:
    """
    Агрегированная торговая статистика
    """

    def __init__(self):
        self.total_trades = 0
        self.successful_trades = 0
        self.total_pnl = Decimal("0")

        self.peak_balance = Decimal("0")
        self.current_drawdown = Decimal("0")
        self.max_drawdown = Decimal("0")

        self.win_rate = Decimal("0")

    def update(self, pnl: Decimal, balance: Decimal):
        self.total_trades += 1
        self.total_pnl += pnl

        if pnl > 0:
            self.successful_trades += 1

        # Peak / drawdown
        if balance > self.peak_balance:
            self.peak_balance = balance
            self.current_drawdown = Decimal("0")
        elif self.peak_balance > 0:
            self.current_drawdown = (
                (self.peak_balance - balance)
                / self.peak_balance
                * Decimal("100")
            )

            if self.current_drawdown > self.max_drawdown:
                self.max_drawdown = self.current_drawdown

        self.win_rate = (
            Decimal(self.successful_trades)
            / Decimal(self.total_trades)
            * Decimal("100")
            if self.total_trades > 0
            else Decimal("0")
        )

    def to_dict(self) -> dict:
        return {
            "total_trades": self.total_trades,
            "successful_trades": self.successful_trades,
            "win_rate": float(self.win_rate),
            "total_pnl": float(self.total_pnl),
            "max_drawdown": float(self.max_drawdown),
        }
