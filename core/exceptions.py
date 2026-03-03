class TradingBotError(Exception):
    """Базовая ошибка торгового бота"""


class ExchangeConnectionError(TradingBotError):
    """Проблемы соединения с биржей"""


class InsufficientBalanceError(TradingBotError):
    """Недостаточно средств"""


class InvalidSignalError(TradingBotError):
    """Некорректный торговый сигнал"""
