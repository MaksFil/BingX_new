# models/positions.py
import time
import logging
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime, timezone
from typing import List, Optional, Dict
from enum import Enum

from models.trading import TrailingStopState

class PositionStatus(Enum):
    OPEN = "open"
    PARTIALLY_CLOSED = "partially_closed"
    CLOSED = "closed"

@dataclass
class Position:
    id: str
    symbol: str
    side: str
    entry: Optional[Decimal]
    tp1: Decimal
    sl: Optional[Decimal]
    margin: Decimal
    notional: Decimal
    quantity: Decimal
    leverage: int
    timestamp: datetime
    tp2: Optional[Decimal] = None
    tp3: Optional[Decimal] = None
    order_id: Optional[str] = None
    remaining_amount: Optional[Decimal] = None
    tp1_hit: bool = False
    tp2_hit: bool = False
    trailing_active: bool = False
    trailing_step_percent: float = 1.0
    trailing_price: Optional[Decimal] = None
    trailing_stop: Optional[Decimal] = None
    pnl: Decimal = Decimal("0")
    pnl_percent: Decimal = Decimal("0")
    auto_sl: bool = False
    status: str = "open"
    mode: str = "safety"

    def __post_init__(self):
        if self.remaining_amount is None:
            self.remaining_amount = self.margin
        self.notional = self.margin * self.leverage

    def calculate_pnl(self, current_price: Decimal):
        if self.entry is None or self.entry == 0:
            return Decimal("0"), Decimal("0")
        try:
            if self.side == "buy":
                price_diff = current_price - self.entry
                pnl_percent = (price_diff / self.entry) * 100
            else:
                price_diff = self.entry - current_price
                pnl_percent = (price_diff / self.entry) * 100

            pnl_usdt = (price_diff / self.entry) * self.notional
            self.pnl = pnl_usdt
            self.pnl_percent = pnl_percent
            return pnl_usdt, pnl_percent

        except (ZeroDivisionError, TypeError) as e:
            logging.error(f"Ошибка расчета PnL: {e}")
            return Decimal("0"), Decimal("0")


class PaperPosition:
    """Виртуальная позиция с полной поддержкой трейлинг-стопа"""

    def __init__(self, symbol: str, entry_price: Decimal, direction: str,
                 size: Decimal, sl: Optional[Decimal], tp_levels: List[Dict],
                 leverage: int = 1, channel_id: Optional[str] = None,
                 channel_name: Optional[str] = None):
        self.id = f"paper_{symbol.replace('/', '')}_{int(time.time())}"
        self.symbol = symbol
        self.entry_price = entry_price
        self.direction = direction.upper()
        self.original_size = size
        self.remaining_size = size
        self.sl = sl
        self.tp_levels = tp_levels  # [{price: Decimal, percent: int, number: int, hit: bool}]
        self.leverage = leverage
        self.status = PositionStatus.OPEN
        self.channel_id = channel_id or "unknown"
        self.channel_name = channel_name or "Unknown Channel"

        self.trailing_stop = TrailingStopState()
        self.realized_pnl = Decimal('0')
        self.closed_at = None
        self.timestamp = datetime.now(timezone.utc)

    def activate_trailing_stop(self, breakeven: bool = True):
        self.trailing_stop.enabled = True
        if breakeven:
            self.trailing_stop.current_level = self.entry_price
        else:
            self.trailing_stop.current_level = self.sl

        if self.direction == 'BUY':
            self.trailing_stop.highest_price = self.entry_price
        else:
            self.trailing_stop.lowest_price = self.entry_price

    def update_trailing_stop(self, current_price: Decimal, trail_percent: Decimal = Decimal('2.0')):
        if not self.trailing_stop.enabled or self.trailing_stop.current_level is None:
            return
        updated = False
        if self.direction == 'BUY':
            if not self.trailing_stop.highest_price or current_price > self.trailing_stop.highest_price:
                self.trailing_stop.highest_price = current_price
                new_stop = current_price * (Decimal('1') - trail_percent / Decimal('100'))
                if new_stop > self.trailing_stop.current_level:
                    self.trailing_stop.current_level = new_stop
                    updated = True
        else:
            if not self.trailing_stop.lowest_price or current_price < self.trailing_stop.lowest_price:
                self.trailing_stop.lowest_price = current_price
                new_stop = current_price * (Decimal('1') + trail_percent / Decimal('100'))
                if new_stop < self.trailing_stop.current_level:
                    self.trailing_stop.current_level = new_stop
                    updated = True

        if updated:
            self.trailing_stop.last_update = datetime.now(timezone.utc)

    def check_trailing_stop_hit(self, current_price: Decimal) -> bool:
        if not self.trailing_stop.enabled or self.trailing_stop.current_level is None:
            return False
        if self.direction == 'BUY':
            hit = current_price <= self.trailing_stop.current_level
        else:
            hit = current_price >= self.trailing_stop.current_level

        return hit

    def close_partial(self, percent: float, close_price: Decimal, reason: str = "TP Hit"):
        if self.status == PositionStatus.CLOSED:
            return
        size_to_close = min(self.remaining_size, self.original_size * (Decimal(str(percent)) / Decimal('100')))
        if size_to_close <= 0:
            return
        pnl = self._calculate_pnl(size_to_close, close_price)
        self.realized_pnl += pnl
        self.remaining_size -= size_to_close
        if self.remaining_size <= Decimal('0.000001'):
            self.remaining_size = Decimal('0')
            self.status = PositionStatus.CLOSED
        else:
            self.status = PositionStatus.PARTIALLY_CLOSED

    def close_full(self, close_price: Decimal, reason: str):
        if self.status == PositionStatus.CLOSED:
            return
        pnl = self._calculate_pnl(self.remaining_size, close_price)
        self.realized_pnl += pnl
        self.remaining_size = Decimal('0')
        self.status = PositionStatus.CLOSED
        self.closed_at = datetime.now(timezone.utc)

    def _calculate_pnl(self, size: Decimal, exit_price: Decimal) -> Decimal:
        if self.entry_price <= 0:
            return Decimal('0')
        notional_value = size * self.leverage
        if self.direction == 'BUY':
            return (exit_price - self.entry_price) * notional_value / self.entry_price
        else:
            return (self.entry_price - exit_price) * notional_value / self.entry_price

    def get_unrealized_pnl(self, current_price: Decimal) -> Decimal:
        if self.status == PositionStatus.CLOSED:
            return Decimal('0')
        return self._calculate_pnl(self.remaining_size, current_price)

    def to_dict(self) -> dict:
        tp1_level = next((level for level in self.tp_levels if level.get('number') == 1), None)
        return {
            'id': self.id,
            'symbol': self.symbol,
            'side': self.direction.lower(),
            'entry': float(self.entry_price),
            'tp1': float(tp1_level['price']) if tp1_level else None,
            'tp2': None,
            'tp3': None,
            'sl': float(self.sl) if self.sl else None,
            'margin': float(self.original_size),
            'remaining_amount': float(self.remaining_size),
            'leverage': self.leverage,
            'pnl': 0,
            'pnl_percent': 0,
            'tp1_hit': tp1_level['hit'] if tp1_level else False,
            'trailing_active': self.trailing_stop.enabled,
            'auto_sl': False,
            'timestamp': self.timestamp.isoformat(),
            'status': self.status.value,
            'trailing_stop': { 'enabled': self.trailing_stop.enabled, 'current_level': float(self.trailing_stop.current_level) if self.trailing_stop.current_level else None } if self.trailing_stop.enabled else None,
            'closed_at': self.closed_at.isoformat() if self.closed_at else None,
            'channel_id': self.channel_id,
            'channel_name': self.channel_name
        }
