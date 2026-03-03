import asyncio
import logging
from collections import deque
from datetime import datetime, UTC
from typing import Dict, Protocol


class RecoveryContext(Protocol):
    async def reconnect_exchange(self): ...
    async def reconnect_telegram(self): ...
    async def update_balance(self): ...
    async def exchange_status_ok(self) -> bool: ...

    @property
    def balance(self) -> float: ...
    @property
    def min_balance(self) -> float: ...


class ErrorRecoverySystem:
    """
    Автоматическое восстановление после ошибок
    """

    def __init__(self, context: RecoveryContext):
        self.context = context
        self.error_history = deque(maxlen=100)
        self.recovery_attempts: Dict[str, int] = {}
        self.max_recovery_attempts = 3

        self.recovery_strategies = {
            "ConnectionError": self._recover_connection,
            "TimeoutError": self._recover_timeout,
            "InsufficientBalanceError": self._recover_balance,
            "ExchangeError": self._recover_exchange,
        }

    async def handle(self, error: Exception, context: Dict) -> bool:
        error_type = type(error).__name__
        key = f"{error_type}:{context.get('operation', 'unknown')}"

        self._log_error(error, context)

        attempts = self.recovery_attempts.get(key, 0) + 1
        self.recovery_attempts[key] = attempts

        if attempts > self.max_recovery_attempts:
            logging.error(f"❌ Max recovery attempts for {key}")
            return False

        handler = self.recovery_strategies.get(error_type)
        if not handler:
            return False

        logging.info(f"🔧 Recovery {attempts}/{self.max_recovery_attempts} for {key}")
        success = await handler(context)

        if success:
            self.recovery_attempts[key] = 0

        return success

    def _log_error(self, error: Exception, context: Dict):
        self.error_history.append({
            "time": datetime.now(UTC).isoformat(),
            "type": type(error).__name__,
            "message": str(error),
            "context": context,
        })

    async def _recover_connection(self, ctx: Dict) -> bool:
        if ctx.get("component") == "telegram":
            await self.context.reconnect_telegram()
            return True

        if ctx.get("component") == "exchange":
            await self.context.reconnect_exchange()
            return True

        return False

    async def _recover_timeout(self, ctx: Dict) -> bool:
        await asyncio.sleep(5)
        return True

    async def _recover_balance(self, ctx: Dict) -> bool:
        await self.context.update_balance()
        return self.context.balance >= self.context.min_balance

    async def _recover_exchange(self, ctx: Dict) -> bool:
        await asyncio.sleep(10)
        return await self.context.exchange_status_ok()

    def stats(self) -> Dict:
        return {
            "total_errors": len(self.error_history),
            "recent": list(self.error_history)[-10:],
            "attempts": dict(self.recovery_attempts),
        }
