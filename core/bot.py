# =========================
# STANDARD LIBRARIES
# =========================
import asyncio
import logging
import time
import traceback
import random
import hashlib
import getpass
import re

from collections import defaultdict
from dataclasses import replace, asdict
from datetime import datetime, timezone, UTC
from decimal import Decimal, InvalidOperation
from typing import (
    Dict,
    List,
    Set,
    Tuple,
    Optional,
)

# =========================
# THIRD-PARTY LIBRARIES
# =========================
import aiohttp
import ccxt

from telethon import TelegramClient, events
from telethon.errors import FloodWaitError

# =========================
# PROJECT IMPORTS
# =========================

from models.trading import TradingConfig
from config import config

from models.positions import Position, PositionStatus
from utils.signal_parser import Signal

from resources.resource_manager import ResourceManager
from utils.signal_parser import SignalParser
from core.validation.signal_validator import SignalValidator
from core.retry_manager import SignalRetryManager
from utils.monitoring import SignalMonitor, error_handler

from core.safety.news_analyzer import AsyncNewsAnalyzer
from core.trading_monitor import TradingMonitor
from core.recovery.error_recovery import ErrorRecoverySystem
from infrastructure.performance import PerformanceOptimizer
from core.metrics import TradingMetrics

from core.database import ImprovedDatabaseManager
from infrastructure.backup_manager import BackupManager
from utils.monitoring import RateLimiter
from api.websocket_manager import websocket_manager

from core.safety.error_handlers import SmartErrorHandler

from core.safety.error_handlers import (
    with_retry,
    with_circuit_breaker,
)

from utils.helpers import (
    normalize_symbol,
    format_symbol_for_exchange,
)

shutdown_event = asyncio.Event()

from infrastructure.reporting.daily_channel_stats import DailyChannelStats

from api.interface import WebInterface  

from core.modes.paper_trading import PaperTradingMode
from core.modes.vst_trading import VSTTradingMode
from core.modes.traiding_mode import TradingMode

from ccxt.base.errors import BadSymbol

class AdvancedTradingBot:
    def __init__(self):
        self.exchange = None
        self.telegram_client = None
        self.db_connection = None

        # Флаги стану
        self.is_running = False
        self.is_initialized = False
        self.shutdown_requested = False
        self.error_handler = SmartErrorHandler()

        # Торгові змінні
        self.open_positions: Dict[str, Position] = {}
        self.closed_positions: Dict[str, Position] = {}
        self.pending_signals: List[Signal] = []
        self.available_markets = set()
        self.monitored_market_signals: Dict[str, Tuple[Signal, float]] = {}

        # Баланси
        self.cached_balance = Decimal("1000")
        self.daily_pnl = Decimal("0")
        self.last_balance_update = datetime.now(UTC)

        # Блокування
        self.position_lock = asyncio.Lock()
        self.signal_lock = asyncio.Lock()
        self.pending_symbols: Set[str] = set()
        self.processing_signals: Set[str] = set()
        self._signal_lock = asyncio.Lock()

        self.message_buffer = []  # Буфер последних сообщений
        self.buffer_max_size = 10  # Максимальное количество сообщений в буфере
        self.buffer_timeout = 30  # Максимальное время между сообщениями в секундах
        self.last_message_time = time.time()

        # Статистика
        self.stats = {
            "signals_received": 0,
            "positions_opened": 0,
            "positions_closed": 0,
            "errors": 0,
        }
        self.processed_message_ids = set()
        self.message_hashes: Dict[str, float] = {}
        self.message_cache_ttl = 600  # 10 минут
        self.message_cache_size = 5000

        # ============================================================
        # КРОК 2: ПОТІМ створюємо об'єкти менеджерів та помічників
        # ============================================================
        self.resource_manager = ResourceManager()
        self.config = TradingConfig()
        self.signal_parser = SignalParser()
        self.news_analyzer = AsyncNewsAnalyzer(config.NEWS_API_KEY)
        self.db_manager = ImprovedDatabaseManager()
        self.web_interface = WebInterface(self)
        self.daily_stats = DailyChannelStats()
        self.trading_monitor = TradingMonitor(self)
        self.error_recovery = ErrorRecoverySystem(self)
        self.performance_optimizer = PerformanceOptimizer(self)

        # ============================================================
        # КРОК 3: Застосовуємо декоратори після створення optimizer
        # ============================================================
        self.get_current_price = self.performance_optimizer.measure_time(
            "get_current_price"
        )(self.performance_optimizer.cached_price()(self.get_current_price))

        # ============================================================
        # КРОК 4: Створюємо допоміжні системи
        # ============================================================
        self.retry_manager = SignalRetryManager()
        self.signal_monitor = SignalMonitor()
        self.metrics = TradingMetrics()
        self.backup_manager = BackupManager("trading_bot.db")
        self.signal_validator = SignalValidator(self.config)
        self.rate_limiter = RateLimiter(max_requests=120, time_window=60)
        self._debug_tickers_logged = False

    # --- НОВЫЙ МЕТОД: Настройка обработчиков событий для WebSocket уведомлений ---
    def setup_websocket_handlers(self):
        """Настройка обработчиков событий для WebSocket уведомлений"""
        async def on_client_connect(connection):
            logging.info("Новое WebSocket подключение")
            await self.broadcast_full_state()

        async def on_client_disconnect(connection, reason):
            logging.info(f"WebSocket отключение: {reason}")

        # --- ИСПРАВЛЕННЫЙ ОБРАБОТЧИК ---
        async def on_client_message(message_data):
            """Обработка команд от WebSocket клиента"""
            try:
                msg_type = message_data.get("type", "")
                if msg_type == "get_positions":
                    await self.broadcast_positions_update()
                elif msg_type == "get_stats":
                    await self.broadcast_stats_update()
                elif msg_type == "close_position":
                    position_id = message_data.get("position_id")
                    if not position_id: return

                    # ✅ ИСПРАВЛЕНО: Добавлена логика для определения режима
                    if self.paper_trading and self.paper_trading.enabled:
                        # Закрываем бумажную позицию
                        logging.info(f"Closing PAPER position via WebSocket: {position_id}")
                        await self.paper_trading.close_paper_position(position_id, "Manual Close via Web")
                    else:
                        # Закрываем реальную позицию
                        logging.info(f"Closing REAL position via WebSocket: {position_id}")
                        await self.close_position_manual(position_id, "Manual Close via Web")

                    # Обновления для интерфейса отправятся автоматически после закрытия
            except Exception as e:
                logging.error(f"Error handling WebSocket message: {e}")

        websocket_manager.add_event_handler("connect", on_client_connect)
        websocket_manager.add_event_handler("disconnect", on_client_disconnect)
        websocket_manager.add_event_handler("message", on_client_message)

    # --- НОВЫЕ МЕТОДЫ ДЛЯ ОТПРАВКИ ДАННЫХ ЧЕРЕЗ WEBSOCKET ---
    async def broadcast_full_state(self):
        """Отправка полного состояния клиентам (ИСПРАВЛЕНО для Paper Trading)"""
        try:
            # Данные о позициях готовятся в broadcast_positions_update,
            # здесь мы его просто вызовем
            await self.broadcast_positions_update()

            # --- НАЧАЛО ИСПРАВЛЕНИЯ ---
            stats_data = {}
            if self.paper_trading and self.paper_trading.enabled:
                paper_stats = self.paper_trading.get_statistics()
                stats_data = {
                    "open_positions": paper_stats.get('open_positions', 0),
                    "closed_positions": paper_stats.get('total_trades', 0),
                    "total_open_pnl": 0,
                    "total_closed_pnl": paper_stats.get('total_pnl', 0),
                    "balance": paper_stats.get('current_balance', 0),
                    "daily_pnl": 0,
                    "demo_mode": True,
                }
            else:
                total_pnl = sum(float(pos.pnl) for pos in self.open_positions.values())
                closed_pnl = sum(float(pos.pnl) for pos in self.closed_positions.values())
                stats_data = {
                    "open_positions": len(self.open_positions),
                    "closed_positions": len(self.closed_positions),
                    "total_open_pnl": total_pnl,
                    "total_closed_pnl": closed_pnl,
                    "balance": float(self.cached_balance),
                    "daily_pnl": float(self.daily_pnl),
                    "demo_mode": self.config.demo_mode,
                }
            # --- КОНЕЦ ИСПРАВЛЕНИЯ ---

            # Отправляем только статистику и конфиг, т.к. позиции уже отправлены
            await websocket_manager.broadcast({
                "type": "stats_update", # Отправляем как stats_update
                "stats": stats_data
            })
            await websocket_manager.broadcast({
                "type": "config_update", # Отдельное событие для конфига
                "config": self.config.to_dict()
            })

        except Exception as e:
            logging.error(f"Error broadcasting full state: {e}")

    async def broadcast_positions_update(self):
        """Отправка обновлений позиций через WebSocket (УПРОЩЕНО)"""
        try:
            positions_data = []
            if self.paper_trading and self.paper_trading.enabled:
                # ✅ Просто используем готовый метод, который уже все посчитал
                positions_data = self.paper_trading.get_open_positions()
            else:
                # Логика для реальных позиций
                for pos in self.open_positions.values():
                    pos_dict = asdict(pos)
                    for key, value in pos_dict.items():
                        if isinstance(value, Decimal):
                            pos_dict[key] = float(value)
                    positions_data.append(pos_dict)

            await websocket_manager.broadcast({
                "type": "positions_update",
                "positions": positions_data
            })
        except Exception as e:
            logging.error(f"Error broadcasting positions: {e}")

    async def check_and_combine_messages(self, new_text: str) -> Optional[str]:
        """ 
        Проверяет, можно ли объединить новое сообщение с предыдущими для создания сигнала
        """
        current_time = time.time()
        
        # Если прошло больше timeout с последнего сообщения, очищаем буфер
        if current_time - self.last_message_time > self.buffer_timeout:
            self.message_buffer = []
            logging.debug("🧹 Буфер очищен по таймауту")
        
        # Добавляем новое сообщение в буфер
        self.message_buffer.append(new_text)
        self.last_message_time = current_time
        
        # Ограничиваем размер буфера
        if len(self.message_buffer) > self.buffer_max_size:
            self.message_buffer = self.message_buffer[-self.buffer_max_size:]
        
        # Пробуем объединить все сообщения в буфере
        combined_text = "\n".join(self.message_buffer)
        
        # Пытаемся распарсить объединенный текст
        signal = self.signal_parser.parse_signal(combined_text)
        
        if signal:
            # Если сигнал распознан, очищаем буфер и возвращаем объединенный текст
            logging.info(f"🎯 Успешно объединены {len(self.message_buffer)} сообщений в сигнал")
            self.message_buffer = []  # ОЧИЩАЕМ БУФЕР
            return combined_text
        
        # Если сигнал не распознан, но буфер большой, возможно пора очистить
        if len(self.message_buffer) >= self.buffer_max_size:
            logging.debug(f"⚠️ Буфер заполнен ({len(self.message_buffer)}), но сигнал не распознан. Очистка.")
            self.message_buffer = []
        
        return None  # Сигнал не готов

    async def broadcast_stats_update(self):
        """Отправка обновлений статистики через WebSocket (ИСПРАВЛЕНО для Paper Trading)"""
        try:
            stats_data = {}
            # --- НАЧАЛО ИСПРАВЛЕНИЯ ---
            if self.paper_trading and self.paper_trading.enabled:
                # Если включен Paper Trading, берем его статистику
                paper_stats = self.paper_trading.get_statistics()
                stats_data = {
                    "open_positions": paper_stats.get('open_positions', 0),
                    "closed_positions": paper_stats.get('total_trades', 0),
                    "total_open_pnl": 0,  # PnL отображается в таблице позиций
                    "total_closed_pnl": paper_stats.get('total_pnl', 0),
                    "balance": paper_stats.get('current_balance', 0),
                    "daily_pnl": 0, # В Paper Trading дневной PnL пока не отслеживается
                    "demo_mode": True,
                }
            else:
                # Старая логика для реальной торговли
                total_pnl = sum(float(pos.pnl) for pos in self.open_positions.values())
                closed_pnl = sum(float(pos.pnl) for pos in self.closed_positions.values())
                stats_data = {
                    "open_positions": len(self.open_positions),
                    "closed_positions": len(self.closed_positions),
                    "total_open_pnl": total_pnl,
                    "total_closed_pnl": closed_pnl,
                    "balance": float(self.cached_balance),
                    "daily_pnl": float(self.daily_pnl),
                    "demo_mode": self.config.demo_mode,
                }
            # --- КОНЕЦ ИСПРАВЛЕНИЯ ---

            await websocket_manager.broadcast({"type": "stats_update", "stats": stats_data})
        except Exception as e:
            logging.error(f"Error broadcasting stats update: {e}")

    async def broadcast_signal_notification(self, signal: Signal):
        """Отправка уведомления о распознанном сигнале через WebSocket"""
        try:
            entry_price = signal.entry_range if signal.entry_range is not None else "Market"
            await websocket_manager.notify(
                title="✅ Распознан сигнал",
                message=f"{signal.symbol} | {signal.side.upper()} | Вход: {entry_price}",
                level="info"
            )
        except Exception as e:
            logging.error(f"Ошибка отправки уведомления о сигнале: {e}")

    async def broadcast_position_event(self, position, event_type, details=""):
        """Уведомление о событиях позиции через WebSocket"""
        try:
            event_messages = {
                "opened": f"Открыта позиция {position.symbol} {position.side.upper()}",
                "tp1_hit": f"TP1 достигнут для {position.symbol}",
                "closed": f"Закрыта позиция {position.symbol}: {details}",
                "trailing_activated": f"Trailing stop активирован для {position.symbol}",
            }

            message = event_messages.get(
                event_type, f"Событие позиции {position.symbol}: {event_type}"
            )

            await websocket_manager.notify(
                title="Позиция",
                message=message,
                level="success" if event_type in ["closed"] else "info",
            )

            # Также отправляем обновление позиций и статистики
            await self.broadcast_positions_update()
            await self.broadcast_stats_update()

        except Exception as e:
            logging.error(f"Error broadcasting position event: {e}")

    def get_enhanced_mock_price(
            self,
            symbol: str,
            hint_price: Optional[Decimal] = None) -> Decimal:
        """Улучшенный генератор mock цен для демо-режима (ИСПРАВЛЕНО)"""
        # Если есть "подсказка" о цене (из сигнала), используем её как основу
        if hint_price and hint_price > 0:
            base_price = hint_price
        else:
            # Старая логика генерации, если подсказки нет
            symbol_hash = int(hashlib.md5(symbol.encode()).hexdigest()[:8], 16)
            base_price = Decimal(
                "0.01") + Decimal(str(symbol_hash % 100)) / Decimal("10000")
            symbol_upper = symbol.upper()

            if "BTC" in symbol_upper:
                base_price = Decimal("50000") + \
                    Decimal(str(symbol_hash % 30000))
            elif "ETH" in symbol_upper:
                base_price = Decimal("3000") + Decimal(str(symbol_hash % 2000))
            elif "BNB" in symbol_upper:
                base_price = Decimal("300") + Decimal(str(symbol_hash % 200))
            elif "SOL" in symbol_upper:
                base_price = Decimal("100") + Decimal(str(symbol_hash % 150))
            elif "ADA" in symbol_upper or "DOT" in symbol_upper or "MATIC" in symbol_upper:
                base_price = Decimal(
                    "1") + Decimal(str(symbol_hash % 10)) / Decimal("10")
            elif "DOGE" in symbol_upper or "SHIB" in symbol_upper:
                base_price = Decimal(
                    "0.01") + Decimal(str(symbol_hash % 100)) / Decimal("10000")
            elif any(coin in symbol_upper for coin in ["USD", "USDT", "USDC", "BUSD"]):
                base_price = Decimal("1.0")
            elif len(symbol.replace("/USDT", "").replace("/USD", "")) <= 3:
                base_symbol = symbol.replace("/USDT", "").replace("/USD", "")
                if base_symbol not in ["BTC", "ETH", "BNB"]:
                    base_price = base_price * Decimal("100")

        # Добавляем небольшую волатильность
        volatility_float = random.uniform(-0.01, 0.01)
        volatility = Decimal(str(volatility_float))
        return base_price * (Decimal("1") + volatility)

    @with_retry(max_retries=3, component="exchange", retry_on=(aiohttp.ClientError, asyncio.TimeoutError, ccxt.NetworkError))
    @with_circuit_breaker(component="exchange")
    async def get_current_price(
            self,
            exchange,
            symbol: str,
            hint_price: Optional[Decimal] = None) -> Optional[Decimal]:
        """
        ФИНАЛЬНАЯ (ОБЪЕДИНЕННАЯ) ВЕРСИЯ:
        - Использует надежный поиск по вариантам (как в "изначальной" версии)
        - Использует fetch_order_book (как в "изначальной" версии)
        - Безопасно возвращает None при ошибке (как в "tb3.py")
        """
        symbol = normalize_symbol(symbol)
        await self.rate_limiter.acquire(f"price_{symbol}")

        # 1. Если биржа не подключена, возвращаем mock (это безопасно)
        if not exchange or not exchange.markets:
            return self.get_enhanced_mock_price(symbol, hint_price=hint_price)

        # 2. Если биржа ПОДКЛЮЧЕНА, мы НИКОГДА не должны возвращать mock.

        # 3. Ваша надежная логика поиска вариантов
        base_symbol = symbol.replace('/USDT', '').replace('-', '')
        symbol_variants = [
            f"{base_symbol}-USDT", # Формат BingX (фьючерсы)
            f"{base_symbol}USDT",   # Формат Binance
            symbol                # Оригинальный формат (BTC/USDT)
        ]
        unique_variants = list(dict.fromkeys(symbol_variants))

        try:
            # 4. Сначала пытаемся получить цену через fetch_ticker
            for symbol_variant in unique_variants:
                try:
                    # Важно: используем params={'type': 'swap'} для гарантии фьючерсов
                    ticker = await exchange.fetch_ticker(symbol_variant, params={'type': 'swap'})
                    if ticker and ticker.get("last"):
                        logging.debug(f"Цена для {symbol} получена через ticker (вариант: {symbol_variant})")
                        return Decimal(str(ticker["last"]))
                except Exception:
                    continue # Пробуем следующий вариант

            # 5. Если fetch_ticker не сработал, пробуем fetch_order_book
            logging.warning(f"Не удалось получить цену для {symbol} через ticker, пробую order book.")
            for symbol_variant in unique_variants:
                try:
                    # Важно: используем params={'type': 'swap'}
                    orderbook = await exchange.fetch_order_book(symbol_variant, limit=1, params={'type': 'swap'})
                    if orderbook['bids'] and orderbook['asks']:
                        price = (Decimal(str(orderbook['bids'][0][0])) + Decimal(str(orderbook['asks'][0][0]))) / 2
                        logging.debug(f"Цена для {symbol} получена через order book (вариант: {symbol_variant})")
                        return price
                except Exception:
                    continue

        except Exception as e:
            # 6. БЕЗОПАСНОСТЬ: Ошибка во время поиска
            logging.error(f"❌ Критическая ошибка получения реальной цены для {symbol}: {e}.")
            return None # Возвращаем None, а НЕ mock-цену

        # 7. БЕЗОПАСНОСТЬ: Если ничего не найдено
        logging.error(f"Не удалось получить цену для {symbol} (фьючерсы) всеми способами.")
        return None # Возвращаем None, а НЕ mock-цену

    async def get_prices_from_tickers(self, exchange, symbols: set) -> Dict[str, Decimal]:
        """Отримує ціни для списку символів (ВИПРАВЛЕНО з новим форматом)."""

        if not symbols or not exchange or not exchange.markets:
            prices = {}
            for symbol in symbols:
                prices[symbol] = self.get_enhanced_mock_price(symbol, None)
            return prices

        try:
            all_tickers = await exchange.fetch_tickers()
            if all_tickers and not self._debug_tickers_logged:
                sample_keys = list(all_tickers.keys())[:10]
                logging.info(f"🔍 DEBUG: Формат ключів з fetch_tickers(): {sample_keys}")
                self._debug_tickers_logged = True

            prices = {}
            for symbol in symbols:
                normalized_symbol = normalize_symbol(symbol)
                exchange_symbol = format_symbol_for_exchange(normalized_symbol, exchange.id)
                quote = normalized_symbol.split('/')[-1]
                colon_symbol = f"{normalized_symbol}:{quote}" # Напр. BTC/USDT:USDT

                found_price = None
                # Ищем по всем известным форматам
                if colon_symbol in all_tickers and all_tickers[colon_symbol].get('last'):
                    found_price = Decimal(str(all_tickers[colon_symbol]['last']))
                elif exchange_symbol in all_tickers and all_tickers[exchange_symbol].get('last'):
                    found_price = Decimal(str(all_tickers[exchange_symbol]['last']))
                elif normalized_symbol in all_tickers and all_tickers[normalized_symbol].get('last'):
                    found_price = Decimal(str(all_tickers[normalized_symbol]['last']))

                if found_price:
                    prices[symbol] = found_price
                else:
                    logging.warning(f"Не вдалося знайти тікер для {symbol} у bulk-запиті, пробую fallback.")
                    # Fallback использует get_current_price, который вернет None при ошибке
                    fallback_price = await self.get_current_price(exchange, symbol, None)
                    if fallback_price:
                        prices[symbol] = fallback_price

            return prices

        except Exception as e:
            logging.error(f"Помилка bulk-запиту fetch_tickers: {e}. Повертаюся до поодиноких запитів.")
            prices = {}
            for symbol in symbols:
                price = await self.get_current_price(exchange, symbol, None)
                if price:
                    prices[symbol] = price
            return prices
 
    async def initialize_telegram_robust(self):
        """Улучшенная инициализация Telegram с обработкой ошибок и интерактивным входом (ИСПРАВЛЕНО)"""
        try:
            # --- НАЧАЛО ИЗМЕНЕНИЙ ---
            # Мы больше не выходим из функции, если API_ID/HASH пустые.
            # Telethon сам обработает это и потребует входа.
            if not TelegramClient:
                # Этот код теперь не должен выполняться из-за исправленного импорта,
                # но оставляем его как дополнительную защиту.
                logging.warning(
                    "⚠️ Библиотека Telethon недоступна. Telegram не будет подключен."
                )
                return

            # Если API_ID или HASH не указаны в конфиге, Telethon сам вызовет ошибку,
            # но мы инициализируем клиент, чтобы дать шанс на интерактивный
            # вход, если сессия уже есть.
            api_id = config.API_ID if config.API_ID else None
            api_hash = config.API_HASH if config.API_HASH else None

            if not api_id or not api_hash:
                logging.warning(
                    "⚠️ API_ID и/или API_HASH не найдены в config.py. Попытка использовать существующую сессию..."
                )

            self.telegram_client = TelegramClient(
                "trading_bot_session",
                api_id,
                api_hash,
                connection_retries=5,
                retry_delay=5,
                timeout=30,
                sequential_updates=True,
            )

            logging.info("🔌 Попытка подключения к Telegram...")
            # --- КОНЕЦ ИЗМЕНЕНИЙ ---

            await self.telegram_client.connect()

            if not await self.telegram_client.is_user_authorized():
                logging.warning("🔑 Требуется авторизация в Telegram.")

                from api.telegram_auth import telegram_auth

                status = await telegram_auth.get_status()

                if not status["connected"]:
                    logging.info("Telegram не авторизован")
                    return

                self.telegram_client = telegram_auth.client

                me = await self.telegram_client.get_me()
                logging.info(
                    f"✅ Telegram подключен: {me.first_name} (@{me.username})"
                )

            me = await self.telegram_client.get_me()
            if me:
                logging.info(
                    f"✅ Telegram успешно подключен как: {me.first_name} (@{me.username})"
                )
                self.setup_telegram_handlers_robust()
                await self.verify_channels()
            else:
                logging.error(
                    "❌ Не удалось проверить авторизацию в Telegram. Проверьте API_ID/HASH в config.py."
                )
                self.telegram_client = None

        except ValueError as e:
            logging.error(
                f"❌ Ошибка конфигурации Telegram: {e}. Убедитесь, что API_ID и API_HASH правильно указаны в config.py."
            )
            self.telegram_client = None
        except Exception as e:
            logging.error(
                f"❌ Критическая ошибка при инициализации Telegram: {e}")
            logging.error(traceback.format_exc())
            self.telegram_client = None

    async def handle_telegram_error(self, event):
        """Обработчик ошибок Telegram"""
        try:
            if hasattr(event, "exception"):
                error = event.exception
                if isinstance(error, ConnectionError):
                    logging.warning("🔄 Переподключение к Telegram...")
                    await self.reconnect_telegram()
        except Exception as e:
            logging.error(f"Ошибка в обработчике ошибок: {e}")

    async def reconnect_telegram(self):
        """Переподключение к Telegram"""
        try:
            if self.telegram_client:
                await self.telegram_client.disconnect()
                await asyncio.sleep(5)
                await self.telegram_client.connect()
                logging.info("✅ Telegram переподключен")
        except Exception as e:
            logging.error(f"❌ Ошибка переподключения: {e}")

    async def verify_channels(self):
        """Проверка доступности каналов"""
        try:
            accessible_channels = []
            for channel_id in config.CHANNEL_IDS:
                try:
                    entity = await self.telegram_client.get_entity(channel_id)
                    accessible_channels.append(channel_id)
                    logging.info(f"✅ Канал {entity.title} доступен")
                except Exception as e:
                    logging.warning(f"⚠️ Канал {channel_id} недоступен: {e}")

            if accessible_channels:
                logging.info(
                    f"📡 Мониторинг {len(accessible_channels)} каналов")
            else:
                logging.warning("⚠️ Ни один канал не доступен для мониторинга")

        except Exception as e:
            logging.error(f"❌ Ошибка проверки каналов: {e}")

    def _get_message_hash(self, text: str, channel: str) -> str:
        """Создает уникальный хеш сообщения для дедупликации"""
        import hashlib
        content = f"{channel}:{text[:200]}"  # Первые 200 символов
        return hashlib.md5(content.encode()).hexdigest()

    def _is_duplicate_message(self, text: str, channel: str, message_id: Optional[int] = None) -> bool:
        """
        Проверяет, не является ли сообщение дубликатом.
        Использует 2 уровня защиты: ID сообщения + хеш содержимого
        """
        # 1. Проверка по ID сообщения (если есть)
        if message_id and message_id in self.processed_message_ids:
            logging.debug(f"🔄 Дубликат по ID: {message_id}")
            return True

        # 2. Проверка по хешу содержимого
        msg_hash = self._get_message_hash(text, channel)
        now = time.time()

        if msg_hash in self.message_hashes:
            last_seen = self.message_hashes[msg_hash]
            if now - last_seen < self.message_cache_ttl:
                logging.debug(f"🔄 Дубликат по хешу: {text[:50]}...")
                return True

        # 3. Регистрация нового сообщения
        if message_id:
            self.processed_message_ids.add(message_id)
            # Ограничение размера кеша
            if len(self.processed_message_ids) > self.message_cache_size:
                # Удаляем 20% старых записей
                to_remove = list(self.processed_message_ids)[:len(self.processed_message_ids) // 5]
                for msg_id in to_remove:
                    self.processed_message_ids.discard(msg_id)

        self.message_hashes[msg_hash] = now

        # Очистка старых хешей
        expired_hashes = [
            h for h, t in self.message_hashes.items()
            if now - t > self.message_cache_ttl
        ]
        for h in expired_hashes:
            del self.message_hashes[h]

        return False
    
    def is_new_signal_start(text):
        return bool(re.search(r'(?:^|\n)[\s]*[\$#]([A-Z]+)', text))

    def setup_telegram_handlers_robust(self):
        """Улучшенная настройка обработчиков с защитой от ошибок и буфером сообщений"""
        if not self.telegram_client or not events:
            return

        @self.telegram_client.on(events.NewMessage(chats=config.CHANNEL_IDS))
        async def robust_message_handler(event):
            try:
                # Получаем информацию о канале
                channel_name = "Unknown"
                channel_id = "unknown"
                if hasattr(event, "chat"):
                    channel_name = getattr(event.chat, "title", str(event.chat_id))
                    channel_id = str(event.chat_id)

                # Получаем ID сообщения
                message_id = None
                if hasattr(event, "message") and hasattr(event.message, "id"):
                    message_id = event.message.id

                # Проверка на старые сообщения
                if hasattr(event.message, "date"):
                    msg_age = (datetime.now(timezone.utc) - event.message.date.replace(tzinfo=timezone.utc)).total_seconds()
                    if msg_age > 300.0:
                        return

                # Извлекаем текст (включая кнопки)
                message_texts: List[str] = []
                if hasattr(event.message, "text") and event.message.text:
                    message_texts.append(event.message.text)
                elif hasattr(event.message, "raw_text") and event.message.raw_text:
                    message_texts.append(event.message.raw_text)
                elif hasattr(event.message, "message") and event.message.message:
                    message_texts.append(event.message.message)

                # Извлечение текста из кнопок
                if hasattr(event.message, "reply_markup") and event.message.reply_markup:
                    try:
                        if hasattr(event.message.reply_markup, "rows"):
                            for row in event.message.reply_markup.rows:
                                if hasattr(row, "buttons"):
                                    for button in row.buttons:
                                        if hasattr(button, "text") and button.text:
                                            message_texts.append(button.text)
                    except Exception as button_error:
                        logging.debug(f"Ошибка извлечения текста из кнопок: {button_error}")

                combined_text = "\n".join(filter(None, message_texts))

                if not combined_text.strip() or len(combined_text.strip()) < 3:
                    return

                # Проверка на дубликаты
                if self._is_duplicate_message(combined_text, channel_id, message_id):
                    logging.debug(f"⏭️ Пропуск дубликата из {channel_name}")
                    return

                logging.info(f"📨 Получено сообщение из {channel_name}: {combined_text}")
                # logging.info(f"📨 Получено сообщение из {channel_name}: {combined_text[:100]}...")

                # === ИСПРАВЛЕННАЯ РАБОТА С БУФЕРОМ ===
                
                current_time = time.time()
                
                # Функция для проверки, является ли сообщение началом нового сигнала
                def is_new_signal_start(text):
                    return bool(re.search(r'(?:^|\n)[\s]*[\$#]([A-Z]+)', text))
                
                if (current_time - self.last_message_time > self.buffer_timeout) or \
                (self.message_buffer and is_new_signal_start(combined_text)):
                    
                    if self.message_buffer:
                        timeout_reason = current_time - self.last_message_time > self.buffer_timeout
                        reason = "по таймауту" if timeout_reason else "из-за начала нового сигнала"
                        logging.debug(f"🧹 Буфер очищен {reason}")
                        self.message_buffer = []
                
                # Добавляем новое сообщение в буфер
                self.message_buffer.append(combined_text)
                self.last_message_time = current_time
                
                # Ограничиваем размер буфера - ИСПРАВЛЕНО!
                if len(self.message_buffer) > self.buffer_max_size:
                    # Оставляем только последние buffer_max_size сообщений
                    self.message_buffer = self.message_buffer[-self.buffer_max_size:]
                    logging.debug(f"📦 Буфер ограничен до {self.buffer_max_size} сообщений")
                
                # Пробуем объединить все сообщения в буфере и распарсить
                full_text = "\n".join(self.message_buffer)
                signal = self.signal_parser.parse_signal(full_text)
                
                if signal:
                    # Сигнал успешно распознан
                    logging.info(f"🎯 Успешно распознан сигнал из {len(self.message_buffer)} сообщений")
                    
                    # Сохраняем копию буфера для логирования (опционально)
                    signal_parts = self.message_buffer.copy()
                    self.message_buffer = []  # ВАЖНО: Очищаем буфер!
                    
                    # Обрабатываем сигнал
                    signal.channel_id = channel_id
                    signal.channel_name = channel_name
                    
                    # Логируем составные части сигнала (для отладки)
                    if len(signal_parts) > 1:
                        logging.debug(f"🧩 Сигнал собран из {len(signal_parts)} частей")
                    
                    try:
                        await self.broadcast_signal_notification(signal)
                    except Exception as broadcast_error:
                        logging.warning(f"Ошибка broadcast уведомления: {broadcast_error}")
                    
                    try:
                        asyncio.create_task(self.process_signal(signal))
                        logging.info(f"✅ Распознан сигнал: {signal.symbol} {signal.side.upper()}")
                        self.stats["signals_received"] += 1
                    except Exception as signal_error:
                        logging.error(f"Ошибка обработки сигнала: {signal_error}")
                
                else:
                    # Сигнал не распознан - логируем состояние буфера
                    buffer_age = current_time - self.last_message_time
                    logging.debug(f"⏳ Буфер содержит {len(self.message_buffer)} сообщений (возраст: {buffer_age:.1f}с), сигнал еще не готов")
                    
                    # Если буфер заполнен, но сигнал не распознан - очищаем
                    if len(self.message_buffer) >= self.buffer_max_size:
                        logging.warning(f"⚠️ Буфер заполнен ({len(self.message_buffer)}), но сигнал не распознан. Очистка.")
                        self.message_buffer = []
                
                # === КОНЕЦ ИСПРАВЛЕНИЯ ===

            except FloodWaitError as flood_error:
                wait_time = flood_error.seconds
                logging.warning(f"🕒 Flood wait в обработчике: {wait_time}с")
                await asyncio.sleep(wait_time + 1)
            except Exception as handler_error:
                logging.error(f"❌ Критическая ошибка в обработчике сообщений: {handler_error}")
                import traceback
                logging.error(traceback.format_exc())


    async def analyze_message_context_safe(self, text: str, event) -> dict:
        """Безопасный анализ контекста сообщения"""
        context = {"symbol": None}
        try:
            if not self.signal_parser.extract_symbol(text):
                # Пытаемся найти символ в предыдущих сообщениях
                try:

                    async def get_context():
                        async for msg in self.telegram_client.iter_messages(
                            event.chat_id, limit=3, offset_id=event.message.id
                        ):
                            if msg and (msg.text or msg.raw_text):
                                prev_text = msg.text or msg.raw_text
                                symbol = self.signal_parser.extract_symbol(
                                    prev_text)
                                if symbol:
                                    context["symbol"] = symbol
                                    logging.debug(
                                        f"Найден символ '{symbol}' из контекста"
                                    )
                                    break

                    # Запускаем получение контекста с таймаутом в 5 секунд
                    await asyncio.wait_for(get_context(), timeout=5.0)

                except asyncio.TimeoutError:
                    logging.warning(
                        "⚠️ Таймаут при получении контекста из Telegram. Пропускаем."
                    )
                except Exception as iter_error:
                    logging.debug(f"Ошибка итерации сообщений: {iter_error}")

        except Exception as context_error:
            logging.debug(f"Общая ошибка анализа контекста: {context_error}")

        return context

    async def initialize_telegram(self):
        """Обертка для вызова улучшенной инициализации"""
        await self.initialize_telegram_robust()

    async def enhanced_parse_with_context(self, text: str, context: dict):
        """Пытается распарсить сигнал, используя дополнительный контекст."""
        signal = self.signal_parser.parse_signal(text)
        if signal:
            return signal

        if context.get("symbol"):
            enriched_text = f"#{context['symbol']}\n{text}"
            logging.info("Повторный парсинг с символом из контекста.")
            return self.signal_parser.parse_signal(enriched_text)

        return None

    async def load_saved_config(self):
        try:
            saved_config = await self.db_manager.load_config()

            if saved_config:
                config_dict = {}

                for key, value in saved_config.items():
                    if hasattr(self.config, key):

                        # Decimal поля
                        if key in [
                            "trade_amount",
                            "min_balance",
                            "tp1_close_percent",
                            "tp2_close_percent",
                            "trailing_distance",
                            "default_sl_percent",
                            "trailing_percent",
                            "trailing_step_percent",
                            "max_price_deviation",
                            "min_signal_confidence",
                        ]:
                            config_dict[key] = Decimal(value)

                        # Int поля
                        elif key in [
                            "max_positions",
                            "leverage",
                            "monitor_interval",
                            "price_check_interval",
                            "position_timeout_hours",
                        ]:
                            config_dict[key] = int(value)

                        # Bool поля
                        elif key in [
                            "auto_stop_loss",
                            "demo_mode",
                            "avoid_news_trading",
                        ]:
                            config_dict[key] = value.lower() == "true"

                        # Mode
                        elif key == "mode":
                            config_dict[key] = value

                        else:
                            config_dict[key] = value

                self.config.update_from_dict(config_dict)
                logging.info("✅ Конфигурация загружена из базы данных")

        except Exception as e:
            logging.warning(f"⚠️ Не удалось загрузить конфигурацию: {e}")

    async def load_positions_from_db(self, db):
        """Загрузка открытых позиций из базы данных при старте."""
        try:
            query = "SELECT * FROM positions WHERE status = 'open'"
            async with db.execute(query) as cursor:
                rows = await cursor.fetchall()
                if not rows:
                    logging.info("Открытых позиций в базе данных не найдено.")
                    return

                columns = [description[0] for description in cursor.description]
                for row in rows:
                    try:
                        pos_data = dict(zip(columns, row))
                        position = Position(
                            id=pos_data.get("id"),
                            symbol=pos_data.get("symbol"),
                            side=pos_data.get("side"),
                            entry=Decimal(str(pos_data.get("entry", "0"))),
                            tp1=Decimal(str(pos_data["tp1"])) if pos_data.get("tp1") is not None else None,
                            tp2=Decimal(str(pos_data["tp2"])) if pos_data.get("tp2") is not None else None,
                            tp3=Decimal(str(pos_data["tp3"])) if pos_data.get("tp3") is not None else None,
                            sl=Decimal(str(pos_data.get("sl", "0"))),
                            margin=Decimal(str(pos_data.get("margin", "0"))),
                            notional=Decimal(str(pos_data.get("notional", "0"))),
                            quantity=Decimal(str(pos_data.get("quantity", "0"))),
                            leverage=int(pos_data.get("leverage", 25)),
                            timestamp=datetime.fromisoformat(pos_data["timestamp"]) if pos_data.get("timestamp") else datetime.now(timezone.utc),
                            remaining_amount=Decimal(str(pos_data.get("remaining_amount", pos_data.get("margin", "0")))),
                            tp1_hit=bool(pos_data.get("tp1_hit", 0)),
                            tp2_hit=bool(pos_data.get("tp2_hit", 0)),
                            trailing_active=bool(pos_data.get("trailing_active", 0)),
                            trailing_step_percent=float(pos_data.get("trailing_step_percent", 0)),
                            trailing_price=Decimal(str(pos_data.get("trailing_price"))) if pos_data.get("trailing_price") is not None else None,
                            trailing_stop=Decimal(str(pos_data["trailing_stop"])) if pos_data.get("trailing_stop") is not None else None,
                            pnl=Decimal(str(pos_data.get("pnl", "0"))),
                            pnl_percent=Decimal(str(pos_data.get("pnl_percent", "0"))),
                            auto_sl=bool(pos_data.get("auto_sl", 0)),
                            status=pos_data.get("status", "open"),
                            modes=pos_data.get("modes", "safety"),
                        )
                        self.open_positions[position.id] = position
                    except (ValueError, TypeError, KeyError, InvalidOperation) as e:
                        row_id = row[columns.index("id")] if "id" in columns and columns.index("id") < len(row) else "unknown"
                        logging.error(f"Ошибка при обработке позиции из БД (ID: {row_id}): {e}")

            logging.info(f"✅ Загружено {len(self.open_positions)} открытых позиций из БД.")
        except Exception as e:
            logging.error(f"❌ Критическая ошибка при загрузке позиций из БД: {e}")
            self.open_positions.clear()

    async def update_available_markets(self):
        """Обновляет список доступных рынков на бирже"""
        try:
            if not self.exchange:
                logging.warning("⚠️ Exchange не инициализирован")
                return

            markets = await self.exchange.load_markets()
            self.available_markets = set(markets.keys())
            logging.info(f"✅ Загружено {len(self.available_markets)} доступных рынков")
        except Exception as e:
            logging.error(f"❌ Ошибка загрузки рынков: {e}")
            self.available_markets = set()

    def is_market_available(self, symbol: str) -> bool:
        """Проверяет доступность символа на бирже с поддержкой разных форматов"""

        # Варианты форматов для поиска
        symbol_variants = [
            symbol.upper(),                           # BAS/USDT
            symbol.upper().replace('/', ''),          # BASUSDT
            symbol.upper().replace('/', '-'),         # BAS-USDT
            symbol.upper().replace('USDT', '') + 'USDT',  # BAS + USDT
            symbol.upper() + ':USDT',                 # BAS:USDT (формат некоторых бирж)
        ]

        # Проверяем все варианты
        for variant in symbol_variants:
            if variant in self.available_markets:
                logging.info(f"✅ Найден рынок: {variant} (исходный: {symbol})")
                return True

        # Дополнительная проверка: поиск по базовой валюте
        base_currency = symbol.split('/')[0].upper()
        for market in self.available_markets:
            if market.startswith(base_currency) and 'USDT' in market:
                logging.info(f"✅ Найден альтернативный рынок: {market} для {symbol}")
                return True

        logging.warning(f"⚠️ Рынок {symbol} НЕДОСТУПЕН на бирже")
        logging.debug(f"Проверенные варианты: {symbol_variants}")
        return False

        return True

    async def validate_signal_before_execution(self, signal: Signal) -> bool:
        """Полная валидация сигнала перед выполнением"""
        # 1. Базовая валидация
        if not signal.validate():
            logging.warning(f"❌ Сигнал {signal.symbol} не прошел базовую валидацию")
            return False

        # 2. Проверка доступности рынка
        if not self.is_market_available(signal.symbol):
            logging.warning(f"⏭️ {signal.symbol} недоступен на бирже. Пропускаем.")
            return False

        return True

    async def process_pending_signals(self, db, exchange):
        """Обработка ожидающих сигналов с передачей db и exchange."""
        if not self.pending_signals:
            return

        async with self.signal_lock:
            signals_to_process = self.pending_signals.copy()
            self.pending_signals.clear()

        logging.info(f"-> [PROCESS] Начинаем обработку {len(signals_to_process)} сигналов в очереди...")
        for signal in signals_to_process:
            logging.info(f"--> [PROCESS] Обрабатывается сигнал для {signal.symbol}...")
            try:
                if signal.entry_range is None:
                    # Для рыночных ордеров получаем цену здесь
                    current_price = await self.get_current_price(exchange, signal.symbol, hint_price=None)
                    if not current_price:
                        logging.warning(f"----> [PROCESS] НЕ УДАЛОСЬ получить цену для рыночного ордера {signal.symbol}. Сигнал пропущен.")
                        continue
                    signal = replace(signal, entry=current_price)

                # <-- Аргументы db и exchange теперь передаются в 'open_position_from_signal'
                await self.open_position_from_signal(db, exchange, signal)

            except Exception as e:
                logging.error(f"❌ Ошибка обработки сигнала {signal.symbol}: {e}\n{traceback.format_exc()}")

    @with_retry(max_retries=2, component="exchange", retry_on=(ccxt.ExchangeError, ccxt.NetworkError))
    @with_circuit_breaker(component="exchange")
    async def open_position_from_signal(self, db, exchange, signal: Signal):
        """Открытие позиции на основе сигнала с использованием переданных db и exchange."""
        try:
            # Проверка лимитов позиций
            async with self.position_lock:
                if len(self.open_positions) >= self.config.max_positions:
                    logging.warning(f"Достигнут лимит в {self.config.max_positions} позиций. Сигнал {signal.symbol} пропущен.")
                    return
                if any(p.symbol == signal.symbol for p in self.open_positions.values()):
                    logging.warning(f"Позиция по {signal.symbol} уже открыта. Сигнал пропущен.")
                    return

            # Логика для демо и реального режима
            if self.config.demo_mode:
                if hasattr(self, 'paper_trading') and self.paper_trading.enabled:
                    await self.paper_trading.open_paper_position(exchange, signal)
            
            # Предторговая валидация
            validation_result = await self.pre_trade_validator.validate_before_trade(exchange, signal)
            if not validation_result.passed:
                logging.error(f"❌ Сделка {signal.symbol} отклонена предторговой проверкой: {validation_result.reason}")
                return

            # Создание объекта Position
            position_id = f"{signal.symbol.replace('/', '')}_{signal.side}_{int(time.time())}"
            margin = self.config.trade_amount
            quantity = (margin * signal.leverage) / signal.entry_range if signal.entry_range > 0 else Decimal(0)

            position = Position(
                id=position_id, symbol=signal.symbol, side=signal.side, entry=signal.entry_range,
                tp1=signal.tp1, sl=signal.sl, margin=margin, notional=margin * signal.leverage,
                quantity=quantity, leverage=signal.leverage, timestamp=datetime.now(UTC),
                tp2=signal.tp2, tp3=signal.tp3, auto_sl=(signal.sl is None)
            )

            # Создание реального ордера на бирже
            order_type = 'limit' if signal.entry_range is not None else 'market'

            if not exchange and not hasattr(self, 'vst_trading'):
                logging.error("Попытка реальной торговли без подключения к бирже.")
                return
            # --- Логика для реального режима ---
            if exchange:
                # Создание реального ордера на бирже
                order = await exchange.create_order(
                    symbol=signal.symbol,
                    type=order_type,
                    side=signal.side,
                    amount=float(quantity),
                    price=float(signal.entry_range) if order_type == 'limit' else None,
                    params={'leverage': signal.leverage}
                )

                # Обновляем позицию данными из ордера и сохраняем
                position.entry = Decimal(str(order.get('average', signal.entry_range)))
                position.order_id = order.get('id')
                self.open_positions[position.id] = position
                await self.save_position_to_db(db, position)
                self.stats["positions_opened"] += 1
                await self.broadcast_position_event(position, "opened")
            elif hasattr(self, 'vst_trading'):
                # Создание реального тестового ордера на бирже
                order = await exchange.create_order(
                    symbol=signal.symbol,
                    type=order_type,
                    side=signal.side,
                    amount=float(quantity),
                    price=float(signal.entry_range) if order_type == 'limit' else None,
                    params={'leverage': signal.leverage}
                )

                # Обновляем позицию данными из ордера и сохраняем
                position.entry = Decimal(str(order.get('average', signal.entry_range)))
                position.order_id = order.get('id')
                self.open_positions[position.id] = position
                await self.save_position_to_db(db, position)
                self.stats["positions_opened"] += 1
                await self.broadcast_position_event(position, "opened")


        except Exception as e:
            logging.error(f"❌ Ошибка в open_position_from_signal: {e}\n{traceback.format_exc()}")
            self.stats["errors"] += 1

    async def process_signal(self, signal_data: Signal):
        """Добавляет распознанный сигнал в очередь для обработки главным циклом."""
        try:
            # === ИСПРАВЛЕНО: Безопасное создание хеша с проверкой None ===
            entry_str = str(signal_data.entry_range) if signal_data.entry_range is not None else "market"
            tp1_str = str(signal_data.tp1) if signal_data.tp1 is not None else "0"
            signal_hash = f"{signal_data.symbol}_{signal_data.side}_{entry_str}_{tp1_str}"

            async with self._signal_lock:
                if signal_hash in self.processing_signals:
                    logging.warning(f"⏭️ Пропуск дубликата сигнала {signal_data.symbol}")
                    return

                self.processing_signals.add(signal_hash)

                # Автоочистка кеша (каждые 100 записей)
                if len(self.processing_signals) > 100:
                    self.processing_signals.clear()
                    logging.debug("🧹 Очищен кеш обрабатываемых сигналов")
            # === КОНЕЦ ИСПРАВЛЕНИЯ ===

            async with self.signal_lock:
                # === ОПТИМИЗИРОВАНО: Проверка дубликатов для лимитных и рыночных ордеров ===
                for existing_signal in self.pending_signals:
                    # Разные символы или направления - пропускаем
                    if existing_signal.symbol != signal_data.symbol:
                        continue
                    if existing_signal.side != signal_data.side:
                        continue

                    # Оба рыночных ордера (entry = None)
                    if existing_signal.entry_range is None and signal_data.entry_range is None:
                        logging.warning(f"⏭️ Сигнал {signal_data.symbol} уже в очереди (рыночный ордер)")
                        return

                    # Оба лимитных ордера (entry указан) - сравниваем цены
                    if existing_signal.entry_range is not None and signal_data.entry_range is not None:
                        price_diff = abs(float(existing_signal.entry_range) - float(signal_data.entry_range))
                        # Разница меньше 0.1% от цены (адаптивный порог)
                        threshold = float(signal_data.entry_range) * 0.001  # 0.1%
                        if price_diff < threshold:
                            logging.warning(
                                f"⏭️ Сигнал {signal_data.symbol} уже в очереди "
                                f"(лимитный {signal_data.entry_range}, разница: {price_diff:.2f})"
                            )
                            return

                    # Один рыночный, один лимитный - это разные ордера, разрешаем
                # === КОНЕЦ ОПТИМИЗАЦИИ ===

                self.pending_signals.append(signal_data)

            logging.info(f"📥 Signal for {signal_data.symbol} added to processing queue")
            logging.info(f"📊 Queue size: {len(self.pending_signals)}")

        except Exception as e:
            logging.error(f"❌ Error adding signal to queue: {e}")
            import traceback
            logging.error(traceback.format_exc())


    async def _execute_signal(self, signal: Signal):
        """
        Выполнение торгового сигнала с полной логикой валидации и принятия решений.
        """
        try:
            logging.info("=" * 50)
            logging.info(f"🔍 DEBUG: _execute_signal STARTED")
            logging.info(f"🔍 DEBUG: Signal symbol: {signal.symbol}")
            logging.info(f"🔍 DEBUG: Signal side: {signal.side}")
            logging.info(f"🔍 DEBUG: Signal entry: {signal.entry_range}")
            logging.info(f"🔍 DEBUG: Signal tp1: {signal.tp1}")
            logging.info(f"🔍 DEBUG: Signal sl: {signal.sl}")
            logging.info("=" * 50)

            logging.info(f"📊 Executing signal for {signal.symbol} {signal.side.upper()}")

            # 1. Валидация сигнала
            logging.info("🔍 DEBUG: Starting signal validation...")
            is_valid, msg = self.signal_validator.validate_signal(signal)
            logging.info(f"🔍 DEBUG: Validation result: {is_valid}, message: {msg}")

            if not is_valid:
                logging.warning(f"❌ Signal validation failed: {msg}")
                return

            logging.info(f"✅ Signal validated: {msg}")

            # 2. Проверка лимита открытых позиций
            logging.info(f"🔍 DEBUG: Checking position limits. Current: {len(self.open_positions)}, Max: {self.config.max_positions}")
            if len(self.open_positions) >= self.config.max_positions:
                logging.warning(
                    f"⚠️ Max positions ({self.config.max_positions}) reached. Signal skipped."
                )
                return

            # 3. Проверка наличия уже открытой позиции по этому символу
            logging.info(f"🔍 DEBUG: Checking for existing position for {signal.symbol}")
            for pos_id, pos in self.open_positions.items():
                if pos.symbol == signal.symbol:
                    logging.warning(
                        f"⚠️ Position for {signal.symbol} already exists. Signal skipped."
                    )
                    return

            # 4. Логирование решения
            logging.info("🔍 DEBUG: Logging decision...")
            try:
                self.decision_logger.log_signal_received(
                    signal,
                    {"valid": True, "message": msg}
                )
                logging.info("🔍 DEBUG: Decision logged successfully")
            except Exception as log_error:
                logging.warning(f"⚠️ Decision logging error: {log_error}")

            # 5. Обработка сигналов с entry (лимитные ордера) vs без entry (рыночные ордера)
            if signal.entry_range is None:
                # Рыночный ордер - открываем сразу
                logging.info(f"🔥 Market order detected for {signal.symbol}")
                logging.info("🔍 DEBUG: Calling open_position_from_signal for MARKET order...")
                await self.open_position_from_signal(signal)
                logging.info("🔍 DEBUG: open_position_from_signal completed for MARKET order")
            else:
                # Лимитный ордер
                logging.info(f"📍 Limit order detected for {signal.symbol} at {signal.entry_range}")
                logging.info("🔍 DEBUG: Calling open_position_from_signal for LIMIT order...")
                await self.open_position_from_signal(signal)
                logging.info("🔍 DEBUG: open_position_from_signal completed for LIMIT order")

            logging.info(f"✅ Signal execution completed for {signal.symbol}")
            logging.info("🔍 DEBUG: _execute_signal FINISHED")

        except Exception as e:
            logging.error(f"❌ Error in _execute_signal for {signal.symbol}: {e}")
            import traceback
            logging.error(f"Traceback: {traceback.format_exc()}")
            self.stats["errors"] += 1

    @error_handler
    async def monitor_positions(self, db, exchange, all_prices: Dict[str, Decimal]):
        """Мониторинг и управление открытыми позициями (принимает готовые цены)."""
        # Эта функция теперь служит "страховкой" на случай падения real-time потока
        # Основная проверка SL/TP происходит в check_position_sl_tp

        if not self.open_positions:
            return

        async with self.position_lock:
            for position_id, position in list(self.open_positions.items()):
                try:
                    current_price = all_prices.get(position.symbol)
                    if not current_price:
                        continue # Цена будет в следующем цикле

                    # Обновляем PnL для UI
                    position.calculate_pnl(current_price)

                except Exception as e:
                    logging.error(f"❌ Ошибка мониторинга PnL {position_id}: {e}")
                    self.stats["errors"] += 1


    async def monitor_market_entries(self, exchange, all_prices: Dict[str, Decimal]):
        """Проверяет сигналы из списка наблюдения (оптимизировано, принимает готовые цены)."""
        if not self.monitored_market_signals:
            return

        for symbol in list(self.monitored_market_signals.keys()): # Итерация по копии ключей
            try:
                if symbol not in self.monitored_market_signals:
                    continue

                signal, creation_time = self.monitored_market_signals[symbol]

                # 3. Проверка таймаута
                if time.time() - creation_time > 300: # 5 минут
                    del self.monitored_market_signals[symbol]
                    continue

                # 4. Получение цены из 'all_prices'
                current_price = all_prices.get(symbol)

                if not current_price:
                    # Fallback, если цена почему-то не пришла
                    current_price = await self.get_current_price(exchange, symbol)
                    if not current_price:
                        logging.debug(f"Не вдалося отримати ціну для моніторингу (market entries) {symbol}")
                        continue

                # 5. Валидация
                temp_signal = replace(signal, entry=current_price)
                is_valid, validation_msg = self.signal_validator.validate_signal(temp_signal)

                if is_valid:
                    logging.info(f"✅ Найден выгодный вход для {symbol} по цене {current_price}.")
                    async with self.signal_lock:
                        self.pending_signals.append(temp_signal)
                    del self.monitored_market_signals[symbol]
                else:
                    logging.debug(f"👀 Мониторинг {symbol}: цена {current_price}, R/R невыгодный. ({validation_msg})")

            except Exception as e:
                logging.error(f"Ошибка мониторинга {symbol}: {e}")
                continue
    @error_handler
    async def initialize(self):
        """Инициализация компонентов, не требующих активных соединений."""
        try:
            logging.info("Инициализация компонентов бота...")

            # Инициализация Paper Trading, если включен демо-режим
            if self.config.demo_mode:
                self.paper_trading = PaperTradingMode(self)
                self.paper_trading.load_state() # Загружаем сохраненные позиции
                self.paper_trading.enable(self.cached_balance)
                self.vst_trading = VSTTradingMode(self)
                self.paper_trading.enabled()
                logging.info("✅ Paper Trading mode доступен")

            # Запускаем фоновый процесс автобэкапов
            asyncio.create_task(self.backup_manager.auto_backup_loop())

            self.is_initialized = True
            logging.info("🎉 Компоненты бота инициализированы!")
            return True
        except Exception as e:
            logging.error(f"❌ Критическая ошибка при инициализации компонентов: {e}")
            return False

    async def _handle_tp1_by_mode(self, db, exchange, position, price):

        mode = TradingMode(position.mode)

        # SAFETY → 60% close + trailing
        if mode == TradingMode.SAFETY:
            close_percent = self.config.tp1_close_percent  # 60%
            await self._partial_close(exchange, position, close_percent)

            position.tp1_hit = True
            position.trailing_active = True
            position.trailing_price = price

        # CLASSIC → 70% close
        elif mode == TradingMode.CLASSIC:
            close_percent = self.config.tp1_close_percent  # 70%
            await self._partial_close(exchange, position, close_percent)

            position.tp1_hit = True

        # PRO-TREND → только частичный TP1
        elif mode == TradingMode.PRO_TREND:
            close_percent = self.config.tp1_close_percent
            await self._partial_close(exchange, position, close_percent)

            position.tp1_hit = True

        await self.update_position_in_db(db, position)

    async def _handle_tp2_by_mode(self, db, exchange, position, price):

        mode = TradingMode(position.mode)

        # CLASSIC → закрыть остаток
        if mode == TradingMode.CLASSIC:
            await self.close_position(db, exchange, position.id, "TP2 Hit", price)

        # PRO-TREND → включить trailing
        elif mode == TradingMode.PRO_TREND:
            position.tp2_hit = True
            position.trailing_active = True
            position.trailing_price = price

        await self.update_position_in_db(db, position)

    async def update_trailing_stop(
            self,
            position: Position,
            current_price: Decimal):
        """Обновление trailing stop"""
        try:
            if position.side == "buy":
                new_stop = current_price * (
                    Decimal("1") - self.config.trailing_percent / 100
                )
                if new_stop > (position.trailing_stop or Decimal("0")):
                    position.trailing_stop = new_stop

                if position.trailing_stop is not None and current_price <= position.trailing_stop:
                    await self.close_position(
                        position.id, "Trailing Stop", current_price
                    )

            else:  # sell
                new_stop = current_price * (
                    Decimal("1") + self.config.trailing_percent / 100
                )
                if position.trailing_stop is None or new_stop < position.trailing_stop:
                    position.trailing_stop = new_stop

                if position.trailing_stop is not None and current_price >= position.trailing_stop:
                    await self.close_position(
                        position.id, "Trailing Stop", current_price
                    )

        except Exception as e:
            logging.error(f"❌ Ошибка обновления trailing stop: {e}")

    async def _partial_close(self, exchange, position, percent):
        close_quantity = position.quantity * (Decimal(percent) / Decimal(100))

        if close_quantity <= 0:
            return

        order = await exchange.create_order(
            symbol=position.symbol,
            type="market",
            side="sell" if position.side == "buy" else "buy",
            amount=float(close_quantity),
        )

        logging.info(f"Partial close: {order['id']}")

    @with_retry(max_retries=4, component="exchange", retry_on=(ccxt.ExchangeError, ccxt.NetworkError)) # Больше попыток, т.к. закрытие критично
    @with_circuit_breaker(component="exchange")
    async def close_position(self, db, exchange, position_id: str, reason: str, current_price: Optional[Decimal] = None):
        """Закрытие позиции с использованием переданных db и exchange."""
        try:
            if position_id not in self.open_positions:
                return

            position = self.open_positions[position_id]

            if not current_price:
                current_price = await self.get_current_price(exchange, position.symbol)
                if not current_price:
                    logging.error(f"Не удалось получить цену для закрытия {position.symbol}")
                    return

            pnl_usdt, pnl_percent = position.calculate_pnl(current_price)
            position.pnl = pnl_usdt
            position.pnl_percent = pnl_percent
            position.status = "closed"

            if self.config.demo_mode:
                if self.paper_trading:
                    self.paper_trading.process_position_close(position, current_price, reason)
                # VST
                close_quantity = position.quantity * (position.remaining_amount / position.margin)
                order = await exchange.create_order(
                    symbol=position.symbol,
                    type="market",
                    side="sell" if position.side == "buy" else "buy",
                    amount=float(close_quantity),
                )
                logging.info(f"[VST] Закрыт ордер для {position.symbol}: {order['id']}")
            elif exchange and position.remaining_amount > 0:
                # Реальный режим
                close_quantity = position.quantity * (position.remaining_amount / position.margin)
                order = await exchange.create_order(
                    symbol=position.symbol,
                    type="market",
                    side="sell" if position.side == "buy" else "buy",
                    amount=float(close_quantity),
                )
                logging.info(f"Закрыт ордер для {position.symbol}: {order['id']}")

            # Перемещаем позицию из открытых в закрытые
            del self.open_positions[position_id]
            self.closed_positions[position_id] = position

            await self.update_position_in_db(db, position)
            self.stats["positions_closed"] += 1
            await self.broadcast_position_event(position, "closed", reason)

        except Exception as e:
            logging.error(f"❌ Ошибка закрытия позиции {position_id}: {e}")
            self.stats["errors"] += 1

    async def close_position_manual(self, db, exchange, position_id: str, reason: str = "Manual"):
        """Ручное закрытие позиции"""
        if position_id in self.open_positions:
            current_price = await self.get_current_price(
                exchange, self.open_positions[position_id].symbol
            )
            await self.close_position(db, exchange, position_id, reason, current_price)

    async def save_position_to_db(self, db, position: Position):
        """Сохраняет новую позицию в БД."""
        await db.execute(
            """
            INSERT INTO positions (id, symbol, side, entry, tp1, tp2, tp3, sl, margin,
                                 notional, quantity, leverage, timestamp, remaining_amount,
                                 auto_sl, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                position.id, position.symbol, position.side, float(position.entry),
                float(position.tp1) if position.tp1 else None,
                float(position.tp2) if position.tp2 else None,
                float(position.tp3) if position.tp3 else None,
                float(position.sl) if position.sl else None,
                float(position.margin), float(position.notional), float(position.quantity),
                position.leverage, position.timestamp.isoformat(),
                float(position.remaining_amount), int(position.auto_sl), position.status
            )
        )
        await db.commit()

    async def update_position_in_db(self, db, position: Position):
        """Обновляет существующую позицию в БД."""
        await db.execute(
            """
            UPDATE positions SET
            remaining_amount = ?, pnl = ?, pnl_percent = ?, status = ?,
            tp1_hit = ?, trailing_active = ?, trailing_stop = ?
            WHERE id = ?
            """,
            (
                float(position.remaining_amount), float(position.pnl), float(position.pnl_percent),
                position.status, int(position.tp1_hit), int(position.trailing_active),
                float(position.trailing_stop) if position.trailing_stop else None,
                position.id
            )
        )
        await db.commit()

    async def update_demo_balance(self, new_balance: Decimal):
        """Обновление демо-баланса через API"""
        if self.config.demo_mode:
            self.cached_balance = new_balance
            logging.info(f"✅ Демо-баланс обновлен: {new_balance} USDT")
            # --- ИЗМЕНЕНИЕ: Уведомление об обновлении баланса ---
            await self.broadcast_stats_update()
            return {"status": "success", "new_balance": float(new_balance)}
        else:
            return {"status": "error", "message": "Только для демо-режима"}

    async def update_balance(self, exchange):
        """Обновление баланса с использованием переданного объекта exchange."""
        try:
            if exchange and not self.config.demo_mode:
                balance = await exchange.fetch_balance()
                usdt_balance = balance["total"].get("USDT", Decimal("0"))
                self.cached_balance = Decimal(str(usdt_balance))

            if datetime.now(UTC).date() != self.last_balance_update.date():
                self.daily_pnl = Decimal("0")
                self.last_balance_update = datetime.now(UTC)
        except Exception as e:
            logging.error(f"❌ Ошибка обновления баланса: {e}")

    async def init_db(self, db):
        await db.execute("""
            CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                entry TEXT,
                tp1 TEXT,
                tp2 TEXT,
                tp3 TEXT,
                sl TEXT,
                margin TEXT,
                notional TEXT,
                quantity TEXT,
                leverage INTEGER,
                timestamp TEXT,
                remaining_amount TEXT,
                tp1_hit INTEGER DEFAULT 0,
                trailing_active INTEGER DEFAULT 0,
                trailing_stop TEXT,
                pnl TEXT DEFAULT '0',
                pnl_percent TEXT DEFAULT '0',
                auto_sl INTEGER DEFAULT 0,
                status TEXT DEFAULT 'open'
            )
        """)
        await db.commit()

    async def run_main_loop(self):
        """
        ФИНАЛЬНАЯ ВЕРСИЯ: Главный цикл, который ВСЕГДА подключается к бирже для получения цен.
        """
        self.is_running = True

        db_path = "trading_bot.db"
        exchange_config = {
            'name': 'bingx',
            'api_key': config.BINGX_API_KEY if hasattr(config, 'BINGX_API_KEY') else 'demo',
            'api_secret': config.BINGX_API_SECRET if hasattr(config, 'BINGX_API_SECRET') else 'demo',
            "vst": config.VST if hasattr(config, 'VST') else False
        }

        logging.info("Запуск главного цикла с менеджером ресурсов...")

        # Теперь мы всегда подключаемся к БД и к бирже
        async with self.resource_manager.manage_database(db_path) as db:
            async with self.resource_manager.manage_exchange(exchange_config) as exchange:

                # Загружаем позиции один раз после всех подключений
                await self.init_db(db)
                await self.load_positions_from_db(db)

                # Запускаем главный цикл, который теперь всегда имеет доступ к 'exchange'
                logging.info(f"Главный цикл запущен. Демо-режим: {self.config.demo_mode}")

                # Запускаем ОБА цикла параллельно
                main_loop_task = asyncio.create_task(self._run_loop_logic(db, exchange))
                stream_manager_task = asyncio.create_task(self.stream_manager_loop(db, exchange))

                # Ждем завершения обоих
                await asyncio.gather(main_loop_task, stream_manager_task)

    async def _run_loop_logic(self, db, exchange):
        """
        ФИНАЛЬНАЯ ВЕРСИЯ: Внутренняя логика бота с исправленным вызовом монитора.
        """
        telegram_check_counter = 0
        update_counter = 0
        alert_check_counter = 0
        daily_report_sent_today = False

        try:
            while not shutdown_event.is_set() and not self.shutdown_requested:
                try:
                    # === ОПТИМИЗАЦИЯ: ПОЛУЧАЕМ ВСЕ ЦЕНЫ ОДИН РАЗ ===
                    symbols_to_check = set()

                    # Собираем символы из открытых позиций
                    async with self.position_lock: # Блокируем на время сбора
                        for pos in self.open_positions.values():
                            symbols_to_check.add(pos.symbol)

                        # Собираем символы из paper-позиций
                        if self.config.demo_mode and hasattr(self, 'paper_trading') and self.paper_trading.enabled:
                            for pos in self.paper_trading.paper_positions.values():
                                if pos.status != PositionStatus.CLOSED:
                                    symbols_to_check.add(pos.symbol)

                    # Собираем символы из "ожидающих" (market entries)
                    for symbol in self.monitored_market_signals.keys():
                        symbols_to_check.add(symbol)

                    # Делаем ОДИН запрос на все
                    all_prices = {}
                    if symbols_to_check:
                        # Используем get_prices_from_tickers, который мы добавили в Исправлении 3
                        all_prices = await self.get_prices_from_tickers(exchange, symbols_to_check)
                    # ===============================================

                    await self.process_pending_signals(db, exchange)

                    # Передаем цены в монитор ожидания
                    await self.monitor_market_entries(exchange, all_prices)

                    retry_signal = await self.retry_manager.process_retries(self.signal_parser)
                    if retry_signal:
                        async with self.signal_lock:
                            self.pending_signals.append(retry_signal)

                    # Передаем цены в монитор позиций (10-секундный "страховочный" вызов)
                    if self.config.demo_mode and hasattr(self, 'paper_trading') and self.paper_trading.enabled:
                        await self.paper_trading.monitor_positions(exchange, all_prices)
                    else:
                        await self.monitor_positions(db, exchange, all_prices)

                    await self.update_balance(exchange)

                    alert_check_counter += 1
                    if alert_check_counter % 10 == 0:
                        await self.trading_monitor.check_alerts()

                    now = datetime.now(timezone.utc)
                    if now.hour == 23 and now.minute == 59:
                        if not daily_report_sent_today:
                            await self.trading_monitor.generate_daily_report()
                            daily_report_sent_today = True
                    else:
                        daily_report_sent_today = False

                    update_counter += 1
                    if update_counter % 5 == 0:
                        await self.broadcast_positions_update()
                        await self.broadcast_stats_update()

                    telegram_check_counter += 1
                    if telegram_check_counter % 30 == 0:
                        await self.check_telegram_health()

                    await asyncio.sleep(self.config.monitor_interval)

                except Exception as e:
                    logging.error(f"❌ Ошибка в главном цикле: {e}")
                    self.stats["errors"] += 1
                    await asyncio.sleep(5)

        except asyncio.CancelledError:
            logging.info("🛑 Главный цикл остановлен")
        except Exception as e:
            logging.error(f"❌ Критическая ошибка в главном цикле: {e}")
        finally:
            self.is_running = False
            logging.info("✅ Главный цикл завершен")

    async def check_telegram_health(self):
        """Проверка здоровья Telegram соединения"""
        try:
            if self.telegram_client and hasattr(
                    self.telegram_client, "is_connected"):
                if not self.telegram_client.is_connected():
                    logging.warning(
                        "⚠️ Telegram отключен, попытка переподключения...")
                    await self.reconnect_telegram()
        except Exception as e:
            logging.debug(f"Ошибка проверки Telegram: {e}")

    async def graceful_shutdown(self):
        """Корректное завершение с улучшенным закрытием Telegram"""
        logging.info("🛑 Запуск процедуры корректного завершения...")
        self.shutdown_requested = True

        # try:
            # Сохраняем состояние Paper Trading (если есть)
        if hasattr(self, 'paper_trading') and self.paper_trading and self.paper_trading.enabled:
            logging.info("💾 Сохранение открытых paper-позиций...")
            self.paper_trading.save_state()

        # ResourceManager сам закроет соединения при выходе из `async with`,
        # но для 100% надежности при экстренном выходе вызываем cleanup.
        if hasattr(self, "resource_manager"):
            await self.resource_manager.cleanup()

        # Улучшенное закрытие Telegram
        # ✅ БЕЗОПАСНОЕ закрытие Telegram
        if hasattr(self, "telegram_client") and self.telegram_client:
            try:
                # Проверяем наличие метода is_connected перед вызовом
                is_connected = False
                try:
                    if hasattr(self.telegram_client, "is_connected"):
                        is_connected = self.telegram_client.is_connected()
                except Exception as check_error:
                    logging.debug(
                        f"Не удалось проверить статус соединения: {check_error}"
                    )
                    # Предполагаем что соединение есть и пытаемся закрыть
                    is_connected = True

                if is_connected:
                    try:
                        await asyncio.wait_for(
                            self.telegram_client.disconnect(), timeout=10.0
                        )
                        logging.info(
                            "✅ Telegram соединение корректно закрыто")
                    except asyncio.TimeoutError:
                        logging.warning(
                            "⚠️ Таймаут при закрытии Telegram (10с)")
                        # Принудительное закрытие
                        try:
                            if hasattr(
                                    self.telegram_client, "_disconnect"):
                                await self.telegram_client._disconnect()
                        except Exception:
                            pass
                    except Exception as disconnect_error:
                        logging.error(
                            f"Ошибка при disconnect: {disconnect_error}")
                else:
                    logging.info("✅ Telegram уже был отключен")

            except Exception as tg_error:

                    logging.error(
                    f"❌ Критическая ошибка закрытия Telegram: {tg_error}"
                )
                # Не прерываем процесс завершения из-за ошибки Telegram


        logging.info("✅ Торговый бот корректно завершил работу")

        # except Exception as e:
        #     logging.error(f"❌ Ошибка при завершении работы: {e}")

    async def check_position_sl_tp(self, db, exchange, position: Position, price: Decimal):

        try:
            # ================================
            # 1️⃣ SL CHECK (highest priority)
            # ================================
            if position.sl is not None:
                if (position.side == "buy" and price <= position.sl) or \
                (position.side == "sell" and price >= position.sl):

                    async with self.position_lock:
                        if position.id in self.open_positions:
                            await self.close_position(db, exchange, position.id, "SL Hit", price)
                    return

            # ================================
            # 2️⃣ TP1
            # ================================
            if not position.tp1_hit and position.tp1:

                tp1_hit = (
                    (position.side == "buy" and price >= position.tp1) or
                    (position.side == "sell" and price <= position.tp1)
                )

                if tp1_hit:
                    await self._handle_tp1_by_mode(db, exchange, position, price)

            # ================================
            # 3️⃣ TP2 (Classic / Pro-Trend)
            # ================================
            if position.tp1_hit and not position.tp2_hit and position.tp2:

                tp2_hit = (
                    (position.side == "buy" and price >= position.tp2) or
                    (position.side == "sell" and price <= position.tp2)
                )

                if tp2_hit:
                    await self._handle_tp2_by_mode(db, exchange, position, price)

            # ================================
            # 4️⃣ TRAILING CHECK
            # ================================
            if position.trailing_active:
                await self._handle_trailing(position, db, exchange, price)

        except Exception as e:
            logging.error(f"TP/SL check error: {e}")

    async def _handle_trailing(self, position, db, exchange, price):

        step = Decimal(position.trailing_step_percent) / Decimal(100)

        if position.side == "buy":

            # обновляем trailing максимум
            if price > position.trailing_price:
                position.trailing_price = price

            trail_level = position.trailing_price * (1 - step)

            if price <= trail_level:
                await self.close_position(db, exchange, position.id, "Trailing Stop Hit", price)

        else:

            if price < position.trailing_price:
                position.trailing_price = price

            trail_level = position.trailing_price * (1 + step)

            if price >= trail_level:
                await self.close_position(db, exchange, position.id, "Trailing Stop Hit", price)

        await self.update_position_in_db(db, position)

    async def watch_symbol_stream(self, db, exchange, symbol: str):
        """Отдельная задача для отслеживания цены ОДНОГО символа (СТРОГО ФЬЮЧЕРСЫ)."""
        logging.info(f"🟢 [STREAM] Запуск real-time мониторинга для {symbol}")

        stream_symbol = format_symbol_for_exchange(symbol, exchange.id)
        stream_active = True

        try:
            # === ИСПРАВЛЕНИЕ: Импортируем MarketNotFound из основного ccxt ===
            import ccxt # Добавьте этот импорт

            await exchange.load_markets()
            market_data = exchange.market(stream_symbol)
            if not market_data or market_data.get('type') != 'swap':
                raise BadSymbol(f"{symbol} ({stream_symbol}) не є ф'ючерсним (swap) ринком.") # Используем ccxt.MarketNotFound

            logging.info(f"✅ [STREAM] {symbol} знайдено на SWAP (ф'ючерси).")

        # === ИСПРАВЛЕНИЕ: Ловим ccxt.MarketNotFound ===
        except BadSymbol as mnf_error: # Ловим ccxt.MarketNotFound
            logging.error(f"❌ [STREAM] Не вдалося знайти ринок ф'ючерсів для {symbol}: {mnf_error}")
            logging.error(f"❌ [STREAM] Цей символ ({symbol}) не підтримується. Зупинка моніторингу.")
            stream_active = False
        except Exception as other_error: # Ловим остальные ошибки
             logging.error(f"❌ [STREAM] Невідома помилка при перевірці ринку {symbol}: {other_error}")
             stream_active = False

        # Головний цикл підписки
        while not shutdown_event.is_set() and stream_active:
            ticker = None
            try:
                ticker = await exchange.watch_ticker(stream_symbol, params={})

                if 'last' in ticker:
                    current_price = Decimal(str(ticker['last']))
                    active_real = False
                    active_paper = False
                    async with self.position_lock:
                        # Реальные позиции
                        real_positions = [p for p_id, p in self.open_positions.items() if p.symbol == symbol]
                        for position in real_positions:
                            await self.check_position_sl_tp(db, exchange, position, current_price)

                        # Paper позиции
                        if hasattr(self, 'paper_trading') and self.paper_trading.enabled:
                            paper_positions = [p for p_id, p in self.paper_trading.paper_positions.items() if p.symbol == symbol and p.status != PositionStatus.CLOSED]
                            for position in paper_positions:
                                await self.paper_trading.check_position_sl_tp(position, current_price)

                        # (Перевірка активності ТУТ, всередині lock, це безпечно)
                        active_real = any(p.symbol == symbol for p in self.open_positions.values())
                        active_paper = (hasattr(self, 'paper_trading') and self.paper_trading.enabled and any(p.symbol == symbol and p.status != PositionStatus.CLOSED for p in self.paper_trading.paper_positions.values()))

                    if not active_real and not active_paper:
                        logging.info(f"🟡 [STREAM] Позиция {symbol} закрыта, остановка мониторинга.")
                        break # Выходим из цикла while

            except ccxt.NetworkError as e:
                logging.warning(f"⚠️ [STREAM] Сетевая ошибка для {symbol}: {e}. Переподключение...")
                await asyncio.sleep(5)
            except Exception as e:
                logging.error(f"❌ [STREAM] Ошибка в потоке {symbol}: {e}")
                await asyncio.sleep(15) # Пауза при неизвестной ошибке

        logging.info(f"🔴 [STREAM] Мониторинг {symbol} завершен.")


    async def stream_manager_loop(self, db, exchange):
        """
        Главный цикл-менеджер real-time потоков (Игнорирует символ после 2 неудачных попыток запуска).
        """
        logging.info("🚀 [STREAM MGR] Запуск менеджера потоков...")
        active_price_streams = {} # { 'symbol': asyncio.Task }
        failed_start_attempts = defaultdict(int) # { 'symbol': count } - Счётчик неудачных попыток

        import ccxt

        try:
            # Загружаем рынки
            try:
                await exchange.load_markets()
            except Exception as load_err:
                logging.error(f"❌ [STREAM MGR] Не удалось загрузить рынки: {load_err}")

            while not shutdown_event.is_set():
                current_symbols = set()
                async with self.position_lock:
                    # Собираем активные символы
                    for pos in self.open_positions.values():
                        current_symbols.add(pos.symbol)
                    if hasattr(self, 'paper_trading') and self.paper_trading.enabled:
                        for pos in self.paper_trading.paper_positions.values():
                            if pos.status != PositionStatus.CLOSED:
                                current_symbols.add(pos.symbol)

                watching_now = set(active_price_streams.keys())

                # === УПРОЩЕННАЯ ЛОГИКА ЗАПУСКА С ПОПЫТКАМИ ===
                # Выбираем символы, которые:
                # 1. Активны сейчас
                # 2. Еще не отслеживаются
                # 3. Количество неудачных попыток < 2
                symbols_to_potentially_start = {
                    s for s in current_symbols
                    if s not in watching_now and failed_start_attempts.get(s, 0) < 2
                }

                for symbol in symbols_to_potentially_start:
                    if symbol in active_price_streams: continue # Двойная проверка

                    logging.debug(f"ℹ️ [STREAM MGR] Попытка #{failed_start_attempts.get(symbol, 0) + 1} запуска для: {symbol}")
                    stream_symbol = format_symbol_for_exchange(symbol, exchange.id)
                    is_valid_swap = False
                    try:
                        # Проверяем, существует ли рынок и является ли он фьючерсным (swap)
                        market_data = exchange.market(stream_symbol)
                        if market_data and market_data.get('type') == 'swap':
                            is_valid_swap = True
                        else:
                            # Рынок есть, но не swap
                            failure_reason = "Не фьючерсный (swap) рынок"
                            raise BadSymbol(failure_reason) # Используем исключение для统一 обработки

                    except BadSymbol as mnf_error:
                        # Рынок не найден или не swap
                        failed_start_attempts[symbol] += 1
                        attempt_count = failed_start_attempts[symbol]
                        logging.error(f"❌ [STREAM MGR] Попытка #{attempt_count} НЕУДАЧНА: Рынок фьючерсов для {symbol} ({stream_symbol}) не найден или невалиден: {mnf_error}.")
                        if attempt_count >= 2:
                             logging.warning(f"⚠️ [STREAM MGR] Символ {symbol} будет проигнорирован до перезапуска бота (2 неудачные попытки).")

                    except Exception as market_check_err:
                        # Другая ошибка при проверке
                        failed_start_attempts[symbol] += 1
                        attempt_count = failed_start_attempts[symbol]
                        logging.error(f"❌ [STREAM MGR] Попытка #{attempt_count} НЕУДАЧНА: Ошибка проверки рынка для {symbol}: {market_check_err}.")
                        if attempt_count >= 2:
                             logging.warning(f"⚠️ [STREAM MGR] Символ {symbol} будет проигнорирован до перезапуска бота (2 неудачные попытки).")

                    # Запускаем поток ТОЛЬКО если рынок валидный
                    if is_valid_swap:
                        logging.info(f"📈 [STREAM MGR] Обнаружена НОВАЯ ВАЛИДНАЯ позиция: {symbol}. Запуск потока.")
                        task = asyncio.create_task(self.watch_symbol_stream(db, exchange, symbol))
                        active_price_streams[symbol] = task
                        # Сбрасываем счетчик неудач при успехе
                        if symbol in failed_start_attempts:
                            del failed_start_attempts[symbol]
                # ==================================

                # 2. Остановка старых потоков
                closed_symbols = watching_now - current_symbols
                for symbol in closed_symbols:
                    if symbol in active_price_streams:
                        logging.info(f"📉 [STREAM MGR] Обнаружена закрытая позиция: {symbol}. Остановка потока.")
                        task = active_price_streams.pop(symbol)
                        if not task.done():
                            task.cancel()
                        # Сбрасываем счетчик неудач при закрытии
                        if symbol in failed_start_attempts:
                            del failed_start_attempts[symbol]

                # 3. Очистка завершившихся задач
                for symbol, task in list(active_price_streams.items()):
                    if task.done():
                        if symbol in active_price_streams:
                             del active_price_streams[symbol]
                        # Сбрасываем счетчик неудач при завершении задачи
                        if symbol in failed_start_attempts:
                            del failed_start_attempts[symbol]

                await asyncio.sleep(5) # Менеджер проверяет список раз в 5 секунд

        except asyncio.CancelledError:
            logging.info("🛑 [STREAM MGR] Получен сигнал отмены.")
        except Exception as e:
            logging.error(f"❌ [STREAM MGR] Критическая ошибка в менеджере потоков: {e}")
        finally:
            # Завершение
            logging.info("🛑 [STREAM MGR] Остановка... Отмена всех потоков.")
            for task in active_price_streams.values():
                task.cancel()
            await asyncio.gather(*active_price_streams.values(), return_exceptions=True)
            logging.info("✅ [STREAM MGR] Все потоки остановлены.")


# ГЛОБАЛЬНЫЕ ОБРАБОТЧИКИ
def signal_handler(signum, frame):
    """Обработчик сигналов завершения"""
    logging.info(f"📞 Получен сигнал {signum}, инициирую завершение...")
    shutdown_event.set()
