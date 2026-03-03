import asyncio
import logging
import aiohttp
from decimal import Decimal
import random
import time
from urllib.parse import urlencode

class DemoExchange:
    """Фиктивная биржа для демо-режима"""
    def __init__(self, name):
        self.name = name
        self.id = name.lower()
        self.markets = {}
        self.symbols = []

    async def load_markets(self):
        """Загрузка контрактов через VST публичный endpoint"""
        url = "https://open-api-vst.bingx.com/openApi/cswap/v1/market/contracts"
        timestamp = int(asyncio.get_event_loop().time() * 1000)
        params = {"timestamp": timestamp}

        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as resp:
                data = await resp.json()

        if data.get("code") != 0 or "data" not in data:
            raise ValueError("Не удалось получить контракты с VST")

        markets = {}
        symbols = []

        for item in data["data"]:
            symbol = item["symbol"]  # пример: BTC-USD
            markets[symbol] = {
                "symbol": symbol,
                "precision": {
                    "price": item.get("pricePrecision", 8),
                    "amount": len(str(item.get("minQty", "1")).split(".")[-1])
                },
                "minQty": float(item.get("minQty", 1)),
                "minTradeValue": float(item.get("minTradeValue", 1)),
                "status": item.get("status", 1)
            }
            symbols.append(symbol)

        self.markets = markets
        self.symbols = symbols

    def market(self, symbol):
        """Эмулируем метод ccxt.market(symbol)"""
        if symbol in self.markets:
            return self.markets[symbol]
        raise ValueError(f"Demo: market {symbol} not found")
    
    async def fetch_ticker(self, symbol):
        symbol_api = symbol.replace("-", "")  # PEPE-USDT -> PEPEUSDT
        url = f"https://api.bingx.com/api/v1/market/ticker?symbol={symbol_api}" # https://open-api.bingx.com/openApi/swap/v2/quote/price?symbol=BTC-USDT
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                data = await resp.json()
        if data.get("code") != 0 or not data.get("data"):
            raise ValueError(f"Не удалось получить публичный тикер для {symbol}")
        last = Decimal(data["data"][0]["last"])
        bid = Decimal(data["data"][0]["bid"])
        ask = Decimal(data["data"][0]["ask"])
        return {"symbol": symbol, "last": last, "bid": bid, "ask": ask}

    async def fetch_tickers(self):
        """
        Получение всех тикеров (swap VST).
        Возвращает dict в формате ccxt.
        """
        url = "https://open-api-vst.bingx.com/openApi/cswap/v1/market/tickers"
        params = {
            "timestamp": int(time.time() * 1000)
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as resp:
                    data = await resp.json()

            if data.get("code") != 0 or "data" not in data:
                logging.warning("Не удалось получить список тикеров")
                return {}

            result = {}

            for item in data["data"]:
                symbol = item.get("symbol")
                if not symbol:
                    continue

                result[symbol] = {
                    "symbol": symbol,
                    "last": Decimal(item.get("lastPrice", "0")),
                    "bid": Decimal(item.get("bidPrice", "0")),
                    "ask": Decimal(item.get("askPrice", "0")),
                    "info": item
                }

            return result

        except Exception as e:
            logging.error(f"Ошибка fetch_tickers: {e}")
            return {}

    async def create_order(self, symbol, type_, side, amount, price=None):
        ticker = await self.fetch_ticker(symbol)
        exec_price = price or ticker['last']
        print(f"[PAPER_OPEN] {side.upper()} {amount} {symbol} по {exec_price}")
        return {
            'id': f'paper_{random.randint(1000,9999)}',
            'status': 'open',
            'symbol': symbol,
            'side': side,
            'price': exec_price,
            'amount': amount
        }

    async def fetch_ticker(self, symbol: str, params: dict = None):
        """
        Получение реальной цены спот-символа через BingX VST.
        symbol: оригинальный символ, например 'BTC/USDT'
        """
        try:
            api_symbol = symbol.replace('/', '-')
            
            query = {
                "symbol": api_symbol,
                "timestamp": int(time.time() * 1000)
            }
            if params and params.get('recvWindow'):
                query['recvWindow'] = params['recvWindow']

            base_url = "https://open-api.bingx.com/openApi/spot/v2/ticker/price"
            full_url = f"{base_url}?{urlencode(query)}"

            async with aiohttp.ClientSession() as session:
                async with session.get(base_url, params=query) as resp:
                    data = await resp.json()
                    logging.info(f"Ответ API: {data}")

            if data.get("code") != 0 or "data" not in data or not data["data"]:
                logging.warning(f"Не удалось получить цену для {symbol} через спот-эндпоинт")
                return None

            # Исправлено: data["data"] — это словарь
            last_price = Decimal(data["data"]["price"])
            return {"last": last_price}

        except Exception as e:
            logging.debug(f"Не удалось получить цену для {symbol}: {e}")
            return None

    async def create_order(self, symbol, type_, side, amount, price=None, params=None):
        return {'id': 'fake_order', 'status': 'open', 'symbol': symbol}

    async def close(self):
        logging.info(f"📄 Demo ({self.name}): closed")
