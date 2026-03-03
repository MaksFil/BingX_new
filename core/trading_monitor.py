import logging
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from typing import Dict, List

from api.websocket_manager import websocket_manager
from models.positions import Position


class TradingMonitor:
    """
    Realtime мониторинг торговли и генерация alerts
    """

    def __init__(self, state):
        """
        state — read-only состояние бота
        """
        self.state = state
        self.alerts: List[Dict] = []

        self.thresholds = {
            "consecutive_losses": 3,
            "hourly_loss_percent": Decimal("2.0"),
            "position_hold_hours": 12,
        }

    async def check_alerts(self) -> List[Dict]:
        alerts = []

        # 1️⃣ подряд идущие убытки
        losses = self._count_consecutive_losses()
        if losses >= self.thresholds["consecutive_losses"]:
            alerts.append(self._alert(
                "warning",
                "Consecutive losses",
                f"{losses} losing trades in a row",
                "Consider pausing trading",
            ))

        # 2️⃣ убыток за час
        hourly_pnl = self._hourly_pnl_percent()
        if hourly_pnl < -self.thresholds["hourly_loss_percent"]:
            alerts.append(self._alert(
                "error",
                "Hourly loss alert",
                f"Lost {abs(hourly_pnl):.2f}% in last hour",
                "Review strategy immediately",
            ))

        # 3️⃣ слишком долгие позиции
        now = datetime.now(timezone.utc)
        for pos in self.state.open_positions.values():
            hours_open = (now - pos.timestamp).total_seconds() / 3600
            if hours_open > self.thresholds["position_hold_hours"]:
                alerts.append(self._alert(
                    "info",
                    "Long-held position",
                    f"{pos.symbol} open for {hours_open:.1f}h",
                    "Consider manual review",
                ))

        for alert in alerts:
            await websocket_manager.notify(
                alert["title"],
                f"{alert['message']}\n{alert['action']}",
                alert["level"],
            )
            self.alerts.append(alert)

        return alerts

    def _count_consecutive_losses(self) -> int:
        count = 0
        for pos in reversed(self.state.closed_positions):
            if pos.pnl < 0:
                count += 1
            else:
                break
        return count

    def _hourly_pnl_percent(self) -> Decimal:
        hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
        pnl = sum(
            pos.pnl for pos in self.state.closed_positions
            if pos.close_timestamp >= hour_ago
        )

        if self.state.balance <= 0:
            return Decimal("0")

        return (pnl / self.state.balance) * 100

    @staticmethod
    def _alert(level: str, title: str, message: str, action: str) -> Dict:
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "title": title,
            "message": message,
            "action": action,
        }
