# models/api.py

from typing import Optional
from decimal import Decimal
from pydantic import BaseModel, Field, field_validator
from core.modes.traiding_mode import TradingMode


# ============================================================
# Trading Config Update (PATCH /api/trading-config)
# ============================================================

class TradingConfigUpdateRequest(BaseModel):
    trade_amount: Optional[Decimal] = None
    max_positions: Optional[int] = None
    leverage: Optional[int] = None
    margin_mode: Optional[str] = None
    min_balance: Optional[Decimal] = None

    tp1_close_percent: Optional[Decimal] = Field(None, ge=1, le=100)
    tp2_close_percent: Optional[Decimal] = Field(None, ge=1, le=100)
    trailing_step_percent: Optional[Decimal] = Field(None, ge=0.1, le=10)

    auto_stop_loss: Optional[bool] = None
    default_sl_percent: Optional[Decimal] = None

    demo_mode: Optional[bool] = None
    avoid_news_trading: Optional[bool] = None

    monitor_interval: Optional[int] = None
    price_check_interval: Optional[int] = None
    position_timeout_hours: Optional[int] = None

    max_price_deviation: Optional[Decimal] = None
    min_signal_confidence: Optional[Decimal] = None

    mode: Optional[TradingMode] = None

    # -------- BUSINESS VALIDATION --------

    @field_validator("tp2_close_percent")
    @classmethod
    def validate_tp_sum(cls, v, info):
        tp1 = info.data.get("tp1_close_percent")
        mode = info.data.get("mode")

        if mode == TradingMode.CLASSIC and tp1 and v:
            if tp1 + v != Decimal("100"):
                raise ValueError("In CLASSIC mode TP1 + TP2 must equal 100")

        return v


# ============================================================
# Close Position
# ============================================================

class ClosePositionRequest(BaseModel):
    position_id: str


# ============================================================
# Trading Signal Model
# ============================================================

class SignalModel(BaseModel):
    symbol: str
    side: str
    entry: Decimal
    tp1: Decimal
    sl: Optional[Decimal] = None
    leverage: int = 25
    tp2: Optional[Decimal] = None
    tp3: Optional[Decimal] = None

    # ---------------- SYMBOL VALIDATION ----------------

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, v: str) -> str:
        if not v or "/" not in v:
            raise ValueError("Invalid symbol format")

        base, quote = v.split("/")

        if not (2 <= len(base) <= 10):
            raise ValueError("Invalid base asset length")

        if quote not in {"USDT", "USD", "BTC", "ETH"}:
            raise ValueError("Invalid quote currency")

        return v.upper()

    # ---------------- SIDE VALIDATION ----------------

    @field_validator("side")
    @classmethod
    def validate_side(cls, v: str) -> str:
        if v.lower() not in {"buy", "sell"}:
            raise ValueError("Side must be buy or sell")
        return v.lower()

    # ---------------- PRICE VALIDATION ----------------

    @field_validator("entry", "tp1", "tp2", "tp3", "sl")
    @classmethod
    def validate_positive_price(cls, v: Optional[Decimal]) -> Optional[Decimal]:
        if v is not None and v <= 0:
            raise ValueError("Price must be positive")
        return v

    # ---------------- LEVERAGE VALIDATION ----------------

    @field_validator("leverage")
    @classmethod
    def validate_leverage(cls, v: int) -> int:
        if not 1 <= v <= 100:
            raise ValueError("Leverage must be between 1 and 100")
        return v