import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, TYPE_CHECKING

# Для корректной работы с типами (Signal) без циклического импорта
if TYPE_CHECKING:
    from your_bot_module import Signal
    
@dataclass
class PreTradeCheckResult:
    """Результат проверки перед сделкой"""
    passed: bool
    reason: str
    details: Dict[str, Any] = field(default_factory=dict)
    risk_score: Decimal = Decimal('0')  # 0-100, где 100 = максимальный риск


class PreTradeValidator:
    """
    Комплексная проверка ПЕРЕД каждой реальной сделкой.
    Это последний рубеж защиты от ошибок.
    """

    def __init__(self, bot):
        self.bot = bot
        self.config = bot.config
        # self.exchange = bot.exchange  <-- Эта строка правильно удалена

        # Критические лимиты
        self.max_spread_percent = Decimal('0.5')
        self.max_price_deviation = Decimal('2.0')
        self.min_liquidity_multiplier = 10

    async def validate_before_trade(
            self, exchange, signal: "Signal") -> PreTradeCheckResult:
        """
        ГЛАВНАЯ функция проверки.
        Проходим ВСЕ проверки последовательно.
        """
        # В этом списке сохранены все ваши оригинальные проверки
        checks = [
            self._check_exchange_connection(exchange),
            self._check_real_balance(exchange),
            self._check_market_exists(exchange, signal.symbol),
            self._check_spread(exchange, signal.symbol),
            self._check_price_deviation(exchange, signal),
            self._check_order_limits(exchange, signal),
            self._check_liquidity(exchange, signal),
            self._check_volatility(exchange, signal.symbol),
            self._check_risk_limits(signal),
            self._check_daily_limits(),
            self._check_no_duplicate_position(signal.symbol),
        ]

        for check_func in checks:
            result = await check_func
            if not result.passed:
                logging.error(f"❌ Pre-trade check FAILED: {result.reason}")
                return result

        logging.info(f"✅ Pre-trade validation PASSED for {signal.symbol}")
        return PreTradeCheckResult(
            passed=True,
            reason="All checks passed",
            risk_score=await self._calculate_risk_score(exchange, signal)
        )

    # Далее идут все ваши методы, исправленные для работы с 'exchange'

    async def _check_exchange_connection(self, exchange) -> PreTradeCheckResult:
        try:
            if not exchange:
                return PreTradeCheckResult(False, "Exchange not initialized")
            await asyncio.wait_for(exchange.fetch_time(), timeout=5.0)
            return PreTradeCheckResult(True, "Exchange connected")
        except asyncio.TimeoutError:
            return PreTradeCheckResult(False, "Exchange connection timeout")
        except Exception as e:
            return PreTradeCheckResult(False, f"Exchange error: {str(e)[:100]}")

    async def _check_real_balance(self, exchange) -> PreTradeCheckResult:
        try:
            balance = await exchange.fetch_balance()
            usdt_free = Decimal(str(balance.get('USDT', {}).get('free', 0)))
            required = self.config.trade_amount
            if usdt_free < required:
                return PreTradeCheckResult(False, f"Insufficient balance: {usdt_free} < {required} USDT")
            if usdt_free - required < Decimal('10'):
                return PreTradeCheckResult(False, f"Trade would leave balance too low: {usdt_free - required} USDT")
            return PreTradeCheckResult(True, "Balance sufficient", {'balance': float(usdt_free)})
        except Exception as e:
            return PreTradeCheckResult(False, f"Balance check error: {e}")

    async def _check_market_exists(self, exchange, symbol: str) -> PreTradeCheckResult:
        try:
            if symbol not in exchange.markets:
                return PreTradeCheckResult(False, f"Market {symbol} not found on exchange")
            market = exchange.market(symbol)
            if not market.get('active', True):
                return PreTradeCheckResult(False, f"Market {symbol} is not active")
            return PreTradeCheckResult(True, "Market exists and active")
        except Exception as e:
            return PreTradeCheckResult(False, f"Market check error: {e}")

    async def _check_spread(self, exchange, symbol: str) -> PreTradeCheckResult:
        try:
            orderbook = await exchange.fetch_order_book(symbol, limit=1)
            best_bid = Decimal(str(orderbook['bids'][0][0]))
            best_ask = Decimal(str(orderbook['asks'][0][0]))
            mid_price = (best_bid + best_ask) / 2
            spread_percent = ((best_ask - best_bid) / mid_price) * 100 if mid_price > 0 else Decimal('0')
            if spread_percent > self.max_spread_percent:
                return PreTradeCheckResult(False, f"Spread too wide: {spread_percent:.3f}% > {self.max_spread_percent}%")
            return PreTradeCheckResult(True, f"Spread acceptable: {spread_percent:.3f}%")
        except Exception as e:
            return PreTradeCheckResult(False, f"Spread check error: {e}")

    async def _check_price_deviation(self, exchange, signal: "Signal") -> PreTradeCheckResult:
        try:
            current_price = await self.bot.get_current_price(exchange, signal.symbol)
            if not current_price or current_price <= 0:
                return PreTradeCheckResult(False, "Cannot get current price")
            if signal.entry is None:
                return PreTradeCheckResult(True, "Market order - no deviation check")
            deviation = abs(current_price - signal.entry) / signal.entry * 100
            if deviation > self.max_price_deviation:
                return PreTradeCheckResult(False, f"Price deviated too much: {deviation:.2f}% > {self.max_price_deviation}%")
            return PreTradeCheckResult(True, f"Price deviation acceptable: {deviation:.2f}%")
        except Exception as e:
            return PreTradeCheckResult(False, f"Price deviation check error: {e}")

    async def _check_order_limits(self, exchange, signal: "Signal") -> PreTradeCheckResult:
        try:
            market = exchange.market(signal.symbol)
            limits = market.get('limits', {})
            current_price = signal.entry or await self.bot.get_current_price(exchange, signal.symbol)
            if not current_price or current_price <= 0:
                return PreTradeCheckResult(False, "Cannot calculate order size")
            order_quantity = self.config.trade_amount / current_price
            min_amount = limits.get('amount', {}).get('min')
            if min_amount and order_quantity < Decimal(str(min_amount)):
                return PreTradeCheckResult(False, f"Order amount too small: {order_quantity} < {min_amount}")
            return PreTradeCheckResult(True, "Order size within limits")
        except Exception as e:
            return PreTradeCheckResult(False, f"Order limits check error: {e}")

    async def _check_liquidity(self, exchange, signal: "Signal") -> PreTradeCheckResult:
        try:
            orderbook = await exchange.fetch_order_book(signal.symbol, limit=10)
            orders = orderbook.get('asks' if signal.side == 'buy' else 'bids', [])
            if not orders:
                return PreTradeCheckResult(False, "No liquidity in orderbook")
            total_volume = sum(Decimal(str(order[1])) for order in orders)
            price = signal.entry or Decimal(str(orders[0][0]))
            our_quantity = self.config.trade_amount / price
            if total_volume < our_quantity * self.min_liquidity_multiplier:
                return PreTradeCheckResult(False, f"Insufficient liquidity")
            return PreTradeCheckResult(True, f"Liquidity sufficient")
        except Exception as e:
            return PreTradeCheckResult(False, f"Liquidity check error: {e}")

    async def _check_volatility(self, exchange, symbol: str) -> PreTradeCheckResult:
        try:
            ohlcv = await exchange.fetch_ohlcv(symbol, '1h', limit=24)
            if len(ohlcv) < 12:
                return PreTradeCheckResult(True, "Insufficient data for volatility check")
            closes = [Decimal(str(candle[4])) for candle in ohlcv]
            changes = [abs((closes[i] - closes[i - 1]) / closes[i - 1]) * 100 for i in range(1, len(closes))]
            max_hourly_change = max(changes) if changes else Decimal('0')
            if max_hourly_change > Decimal('10'):
                return PreTradeCheckResult(False, f"EXTREME volatility detected: {max_hourly_change:.2f}% in 1h")
            return PreTradeCheckResult(True, f"Volatility acceptable")
        except Exception as e:
            return PreTradeCheckResult(False, f"Cannot verify volatility: {e}")

    # ВАША ОРИГИНАЛЬНАЯ ЛОГИКА, КОТОРАЯ БЫЛА ПРОПУЩЕНА, ТЕПЕРЬ ВОССТАНОВЛЕНА
    async def _check_risk_limits(self, signal: "Signal") -> PreTradeCheckResult:
        try:
            if not hasattr(self.bot, 'risk_manager'):
                return PreTradeCheckResult(True, "No risk manager configured")
            risk_manager = self.bot.risk_manager
            is_stopped, stop_msg = risk_manager.check_emergency_stop(self.bot.cached_balance)
            if is_stopped:
                return PreTradeCheckResult(False, f"Emergency stop active: {stop_msg}")
            can_open, risk_msg = risk_manager.can_open_position(self.config.trade_amount, self.bot.cached_balance)
            if not can_open:
                return PreTradeCheckResult(False, f"Risk check failed: {risk_msg}")
            return PreTradeCheckResult(True, "Risk limits OK")
        except Exception as e:
            return PreTradeCheckResult(False, f"Risk check error: {e}")

    async def _check_daily_limits(self) -> PreTradeCheckResult:
        try:
            today = datetime.now(timezone.utc).date()
            today_positions = [pos for pos in self.bot.closed_positions.values() if pos.timestamp.date() == today]
            max_daily_trades = 10
            if len(today_positions) >= max_daily_trades:
                return PreTradeCheckResult(False, f"Daily trade limit reached: {len(today_positions)}/{max_daily_trades}")
            recent_closed = list(self.bot.closed_positions.values())[-5:]
            consecutive_losses = 0
            for pos in reversed(recent_closed):
                if pos.pnl < 0:
                    consecutive_losses += 1
                else:
                    break
            max_consecutive_losses = 3
            if consecutive_losses >= max_consecutive_losses:
                return PreTradeCheckResult(False, f"Too many consecutive losses: {consecutive_losses}")
            return PreTradeCheckResult(True, f"Daily limits OK")
        except Exception as e:
            return PreTradeCheckResult(False, f"Daily limits check error: {e}")

    async def _check_no_duplicate_position(self, symbol: str) -> PreTradeCheckResult:
        try:
            if symbol in [pos.symbol for pos in self.bot.open_positions.values()]:
                return PreTradeCheckResult(False, f"Position already open for {symbol}")
            return PreTradeCheckResult(True, "No duplicate position")
        except Exception as e:
            return PreTradeCheckResult(False, f"Duplicate check error: {e}")

    async def _calculate_risk_score(self, exchange, signal: "Signal") -> Decimal:
        risk_score = Decimal('0')
        try:
            if signal.entry:
                current_price = await self.bot.get_current_price(exchange, signal.symbol)
                if current_price:
                    deviation = abs(current_price - signal.entry) / signal.entry * 100
                    risk_score += min(deviation * 10, Decimal('20'))
            try:
                ohlcv = await exchange.fetch_ohlcv(signal.symbol, '1h', limit=24)
                if len(ohlcv) >= 12:
                    closes = [Decimal(str(c[4])) for c in ohlcv]
                    changes = [abs((closes[i] - closes[i - 1]) / closes[i - 1]) * 100 for i in range(1, len(closes))]
                    avg_vol = sum(changes) / len(changes) if changes else Decimal('0')
                    risk_score += min(avg_vol * 6, Decimal('30'))
            except Exception:
                risk_score += Decimal('15')
            if signal.sl and signal.entry:
                risk = abs(signal.entry - signal.sl)
                reward = abs(signal.tp1 - signal.entry)
                rr_ratio = reward / risk if risk > 0 else Decimal('0')
                if rr_ratio < Decimal('1'): risk_score += Decimal('30')
                elif rr_ratio < Decimal('2'): risk_score += Decimal('20')
                elif rr_ratio < Decimal('3'): risk_score += Decimal('10')
            else:
                risk_score += Decimal('15')
            return min(risk_score, Decimal('100'))
        except Exception as e:
            logging.error(f"Error calculating risk score: {e}")
            return Decimal('50')