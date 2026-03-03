import time
import logging
from decimal import Decimal
from typing import Optional

class RealPriceFetcher:
    """Получение реальных цен с множественными источниками"""

    def __init__(self, exchange):
        self.exchange = exchange
        self.price_cache = {}
        self.cache_duration = 5  # секунд
        self.failed_symbols = set()

    async def get_real_price(self, symbol: str) -> Optional[Decimal]:
        """Получение реальной цены с кэшированием"""
        if symbol in self.price_cache:
            price, timestamp = self.price_cache[symbol]
            if time.time() - timestamp < self.cache_duration:
                return price

        # Попытка получить цену
        try:
            ticker = await self.exchange.fetch_ticker(symbol)
            if ticker and ticker.get("last"):
                price = Decimal(str(ticker["last"]))
                self.price_cache[symbol] = (price, time.time())
                self.failed_symbols.discard(symbol)
                return price
        except Exception as e:
            logging.warning(f"Failed to fetch ticker for {symbol}: {e}")

        try:
            orderbook = await self.exchange.fetch_order_book(symbol, limit=1)
            if orderbook.get("bids") and orderbook.get("asks"):
                bid = Decimal(str(orderbook["bids"][0][0]))
                ask = Decimal(str(orderbook["asks"][0][0]))
                price = (bid + ask) / 2
                self.price_cache[symbol] = (price, time.time())
                return price
        except Exception as e:
            logging.warning(f"Failed to fetch orderbook for {symbol}: {e}")

        self.failed_symbols.add(symbol)
        logging.error(f"❌ Cannot get real price for {symbol}")
        return None

    def validate_price(self, price: Decimal, symbol: str) -> bool:
        """Проверка адекватности цены"""
        if price <= 0:
            return False
        if price > Decimal("1000000"):
            logging.warning(f"Price {price} seems too high for {symbol}")
            return False
        if price < Decimal("0.00000001"):
            logging.warning(f"Price {price} seems too low for {symbol}")
            return False
        return True
