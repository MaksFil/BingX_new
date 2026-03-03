import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Tuple

@dataclass
class SlippageConfig:
    """Конфигурация защиты от слиппеджа"""
    max_slippage_percent: Decimal = Decimal("0.5")  # 0.5% максимальный слиппедж
    max_spread_percent: Decimal = Decimal("0.3")  # 0.3% максимальный спред
    use_limit_orders: bool = True
    limit_order_offset_percent: Decimal = Decimal("0.1")  # Отступ от текущей цены


class SlippageProtection:
    """Защита от слиппеджа с использованием limit ордеров"""

    def __init__(self, config: Optional[SlippageConfig] = None):
        self.config = config or SlippageConfig()

    async def check_spread(self, symbol: str, exchange) -> Tuple[bool, Decimal, str]:
        """Проверка спреда перед входом"""
        try:
            orderbook = await exchange.fetch_order_book(symbol, limit=1)

            if not orderbook.get("bids") or not orderbook.get("asks"):
                return False, Decimal("0"), "Empty orderbook"

            best_bid = Decimal(str(orderbook["bids"][0][0]))
            best_ask = Decimal(str(orderbook["asks"][0][0]))

            mid_price = (best_bid + best_ask) / 2
            spread = best_ask - best_bid
            spread_percent = (spread / mid_price) * 100

            if spread_percent > self.config.max_spread_percent:
                msg = f"Spread too wide: {spread_percent:.3f}% (limit: {self.config.max_spread_percent}%)"
                logging.warning(f"⚠️ {msg}")
                return False, spread_percent, msg

            return True, spread_percent, "OK"

        except Exception as e:
            logging.error(f"Error checking spread: {e}")
            return False, Decimal("0"), f"Error: {e}"

    def calculate_limit_price(self, current_price: Decimal, side: str) -> Decimal:
        """Расчет цены для limit ордера"""
        offset = self.config.limit_order_offset_percent / 100
        if side == "buy":
            return current_price * (Decimal("1") + offset)
        else:
            return current_price * (Decimal("1") - offset)

    def validate_execution_price(self, expected_price: Decimal, executed_price: Decimal, side: str) -> Tuple[bool, str]:
        """Валидация цены исполнения"""
        if side == "buy":
            slippage = (executed_price - expected_price) / expected_price * 100
        else:
            slippage = (expected_price - executed_price) / expected_price * 100

        if abs(slippage) > self.config.max_slippage_percent:
            msg = f"Slippage {slippage:.3f}% exceeds limit {self.config.max_slippage_percent}%"
            return False, msg

        return True, f"Slippage: {slippage:.3f}%"
