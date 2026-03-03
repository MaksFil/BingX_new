from enum import Enum

class TradingMode(str, Enum):
    SAFETY = "safety"
    CLASSIC = "classic"
    PRO_TREND = "pro_trend"