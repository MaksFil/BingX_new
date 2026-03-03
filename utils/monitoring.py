import time
import asyncio
import functools
import logging
import traceback
from collections import deque, defaultdict
from datetime import datetime, timezone
from typing import Dict, List


class SignalMonitor:
    """Мониторинг обработанных сигналов и анализ пропущенных"""

    def __init__(self):
        self.processed_messages = deque(maxlen=1000)
        self.failed_parsing = deque(maxlen=500)
        self.signal_keywords = [
            "long", "short", "buy", "sell",
            "tp", "sl", "entry", "target", "#"
        ]

    async def log_message(self, text: str, success: bool, metadata: dict):
        """Логирует каждое обработанное сообщение"""
        self.processed_messages.append(
            (text, success, metadata, datetime.now(timezone.utc))
        )
        if not success:
            self.failed_parsing.append(text)

    async def analyze_missed_signals(self) -> dict:
        """Анализирует сообщения, которые могли быть пропущены"""
        total_processed = len(self.processed_messages)
        if total_processed == 0:
            return {
                "total_processed": 0,
                "potential_misses": 0,
                "miss_rate_percent": 0.0,
                "common_missed_keywords": {},
            }

        potential_misses = 0

        for text in self.failed_parsing:
            text_lower = text.lower()
            keyword_hits = sum(
                1 for keyword in self.signal_keywords if keyword in text_lower
            )
            if keyword_hits >= 3:  # считаем пропущенным, если есть 3+ ключевых слова
                potential_misses += 1

        miss_rate_percent = (potential_misses / total_processed) * 100 if total_processed > 0 else 0

        return {
            "total_processed": total_processed,
            "potential_misses": potential_misses,
            "miss_rate_percent": miss_rate_percent,
        }


def error_handler(func):
    """Декоратор для обработки ошибок"""

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            logging.error(f"Error in {func.__name__}: {e}")
            logging.error(f"Traceback: {traceback.format_exc()}")
            raise

    return wrapper


class RateLimiter:
    """Простой асинхронный лимитер запросов"""

    def __init__(self, max_requests: int = 10, time_window: int = 60):
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests: Dict[str, List[float]] = defaultdict(list)

    async def acquire(self, key: str = "default"):
        """Получить разрешение на запрос"""
        now = time.time()

        # Очищаем старые запросы
        self.requests[key] = [
            req_time for req_time in self.requests[key]
            if now - req_time < self.time_window
        ]

        if len(self.requests[key]) >= self.max_requests:
            sleep_time = self.time_window - (now - self.requests[key][0])
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)

        self.requests[key].append(now)
