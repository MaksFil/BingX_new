import logging
from decimal import Decimal
from typing import Tuple

from models.trading import TradingConfig
from utils.signal_parser import Signal

class SignalValidator:
    """
    Базовая бизнес-валидация торговых сигналов
    """

    def __init__(self, config: TradingConfig):
        self.config = config

    def validate(self, signal: Signal) -> Tuple[bool, str]:
        if not signal.validate():
            return False, self._build_validation_error(signal)

        if signal.sl:
            rr = self._risk_reward(signal)
            if rr < self.config.min_risk_reward:
                return False, f"Poor risk/reward ratio: {rr:.2f}"

        return True, "Signal is valid"

    def _build_validation_error(self, signal: Signal) -> str:
        details = []

        if signal.side == "buy":
            if signal.tp1 <= signal.entry_range:
                details.append("TP1 <= Entry")
            if signal.sl and signal.sl >= signal.entry_range:
                details.append("SL >= Entry")
        else:
            if signal.tp1 >= signal.entry_range:
                details.append("TP1 >= Entry")
            if signal.sl and signal.sl <= signal.entry_range:
                details.append("SL <= Entry")

        return "Basic validation failed: " + ", ".join(details)

    @staticmethod
    def _risk_reward(signal: Signal) -> float:
        if not signal.sl:
            return 0.0

        if signal.side == "buy":
            risk = signal.entry_range - signal.sl
            reward = signal.tp1 - signal.entry_range
        else:
            risk = signal.sl - signal.entry_range
            reward = signal.entry_range - signal.tp1

        return float(reward / risk) if risk > 0 else 0.0

class EnhancedSignalValidator:
    """Расширенная валидация сигналов с confidence threshold"""

    def __init__(self, min_confidence: Decimal = Decimal("0.8")):
        self.min_confidence = min_confidence
        self.volatility_window = 100  # свечей для расчета волатильности

    async def validate_signal_comprehensive(
        self, signal, exchange, price_fetcher
    ) -> Tuple[bool, Decimal, str]:
        """Комплексная валидация сигнала"""
        confidence = Decimal("1.0")
        reasons = []

        if not signal.validate():
            return False, Decimal("0"), "Basic validation failed"

        if signal.confidence < self.min_confidence:
            confidence *= Decimal("0.5")
            reasons.append(f"Low signal confidence: {signal.confidence}")

        real_price = await price_fetcher.get_real_price(signal.symbol)
        if not real_price:
            return False, Decimal("0"), "Cannot get real price"

        if not price_fetcher.validate_price(real_price, signal.symbol):
            return False, Decimal("0"), "Invalid price range"

        if signal.entry:
            price_diff = abs(signal.entry - real_price) / real_price * 100
            if price_diff > Decimal("5.0"):
                confidence *= Decimal("0.7")
                reasons.append(f"Large price deviation: {price_diff:.2f}%")

        if signal.sl:
            risk = abs(signal.entry - signal.sl)
            reward = abs(signal.tp1 - signal.entry)
            rr_ratio = reward / risk if risk > 0 else Decimal("0")
            if rr_ratio < Decimal("1.5"):
                confidence *= Decimal("0.8")
                reasons.append(f"Low R/R: {rr_ratio:.2f}")

        try:
            volatility_ok, vol_msg = await self.check_volatility(signal.symbol, exchange)
            if not volatility_ok:
                confidence *= Decimal("0.9")
                reasons.append(vol_msg)
        except Exception as e:
            logging.debug(f"Volatility check failed: {e}")

        final_confidence = confidence * signal.confidence
        if final_confidence < self.min_confidence:
            msg = f"Final confidence {final_confidence:.2f} < threshold {self.min_confidence}. " + ", ".join(reasons)
            return False, final_confidence, msg

        return True, final_confidence, "Signal validated"

    async def check_volatility(self, symbol: str, exchange) -> Tuple[bool, str]:
        """Проверка волатильности"""
        try:
            ohlcv = await exchange.fetch_ohlcv(symbol, "1h", limit=24)
            if len(ohlcv) < 20:
                return True, "Insufficient data for volatility"

            closes = [Decimal(str(candle[4])) for candle in ohlcv]
            returns = [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes))]
            mean_return = sum(returns) / Decimal(len(returns))
            variance = sum([(r - mean_return) ** Decimal('2') for r in returns]) / Decimal(len(returns))
            volatility = variance ** Decimal("0.5")

            if volatility > Decimal("0.1"):
                return False, f"High volatility: {volatility:.4f}"

            return True, "Volatility OK"
        except Exception as e:
            logging.debug(f"Volatility check error: {e}")
            return True, "Volatility check skipped"
