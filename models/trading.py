# models/trading.py
import logging
from dataclasses import dataclass, asdict, field
from decimal import Decimal
from datetime import datetime, timezone
from typing import Optional, Tuple

from core.modes.traiding_mode import TradingMode

@dataclass
class TradingConfig:
    trade_amount: Decimal = Decimal("50")
    max_positions: int = 20
    leverage: int = 25
    margin_mode: str = "ISOLATED"
    min_balance: Decimal = Decimal("100")
    trailing_percent: Decimal = Decimal("40")
    trailing_distance: Decimal = Decimal("1.0")
    auto_stop_loss: bool = True
    default_sl_percent: Decimal = Decimal("5.0")
    demo_mode: bool = True
    avoid_news_trading: bool = True
    monitor_interval: int = 10
    price_check_interval: int = 15
    position_timeout_hours: int = 24
    max_price_deviation: Decimal = Decimal("1.5")
    min_signal_confidence: Decimal = Decimal("0.5")
    mode: str = TradingMode.SAFETY.value

    tp1_close_percent: Decimal = Decimal("60")
    tp2_close_percent: Decimal = Decimal("30")

    trailing_step_percent: Decimal = Decimal("1")

    def update_from_dict(self, config_dict: dict):
        for key, value in config_dict.items():
            if hasattr(self, key):
                if key in [
                    "trade_amount",
                    "min_balance",
                    "tp1_close_percent",
                    "trailing_distance",
                    "default_sl_percent",
                    "trailing_percent",
                    "max_price_deviation",
                    "min_signal_confidence",
                ]:
                    setattr(self, key, Decimal(str(value)))
                else:
                    setattr(self, key, value)

    def to_dict(self) -> dict:
        result = {}
        for key, value in asdict(self).items():
            if isinstance(value, Decimal):
                result[key] = float(value)
            else:
                result[key] = value
        return result


@dataclass
class TrailingStopState:
    enabled: bool = False
    current_level: Optional[Decimal] = None
    highest_price: Optional[Decimal] = None  # Для BUY
    lowest_price: Optional[Decimal] = None   # Для SELL
    last_update: Optional[datetime] = None
