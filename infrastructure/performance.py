import time
import logging
import functools
from collections import defaultdict
from typing import Dict


class PerformanceOptimizer:
    """
    Оптимизация производительности бота
    """

    def __init__(self, bot):
        self.bot = bot

        # Кэш для часто используемых данных
        self.price_cache = {}
        self.market_cache = {}
        self.cache_ttl = 5  # секунд

        # Метрики производительности
        self.performance_metrics = {
            "function_calls": defaultdict(int),
            "function_times": defaultdict(list),
            "cache_hits": 0,
            "cache_misses": 0,
        }

    def cached_price(self):
        """
        """

        def decorator(func):
            @functools.wraps(func)
            async def wrapper(*args, **kwargs):
                # args[0] это 'self', args[1] это 'symbol'
                symbol = args[1] if len(args) > 1 else kwargs.get("symbol")
                if not symbol:
                    return await func(*args, **kwargs)

                cache_key = f"price_{symbol}_{int(time.time() / self.cache_ttl)}"

                if cache_key in self.price_cache:
                    self.performance_metrics["cache_hits"] += 1
                    return self.price_cache[cache_key]

                self.performance_metrics["cache_misses"] += 1
                result = await func(*args, **kwargs)
                self.price_cache[cache_key] = result

                # Очистка старого кэша
                if len(self.price_cache) > 1000:
                    oldest_keys = sorted(self.price_cache.keys())[:500]
                    for key in oldest_keys:
                        if key in self.price_cache:
                            del self.price_cache[key]

                return result

            return wrapper

        return decorator

    def measure_time(self, func_name: str):
        """Декоратор для измерения времени выполнения"""

        def decorator(func):
            @functools.wraps(func)
            async def wrapper(*args, **kwargs):
                start_time = time.time()
                try:
                    result = await func(*args, **kwargs)
                    return result
                finally:
                    execution_time = time.time() - start_time
                    self.performance_metrics["function_calls"][func_name] += 1
                    self.performance_metrics["function_times"][func_name].append(
                        execution_time)

                    # Предупреждение о медленных функциях
                    if execution_time > 1.0:  # Больше 1 секунды
                        logging.warning(
                            f"⚠️ Slow function: {func_name} took {execution_time:.2f}s"
                        )

            return wrapper

        return decorator

    def get_performance_report(self) -> Dict:
        """Отчёт о производительности"""
        report = {
            "cache_stats": {
                "hits": self.performance_metrics["cache_hits"],
                "misses": self.performance_metrics["cache_misses"],
                "hit_rate": (
                    (
                        self.performance_metrics["cache_hits"]
                        / (
                            self.performance_metrics["cache_hits"]
                            + self.performance_metrics["cache_misses"]
                        )
                        * 100
                    )
                    if (
                        self.performance_metrics["cache_hits"]
                        + self.performance_metrics["cache_misses"]
                    )
                    > 0
                    else 0
                ),
            },
            "function_stats": {},
        }

        for func_name, times in self.performance_metrics["function_times"].items(
        ):
            if times:
                report["function_stats"][func_name] = {
                    "calls": self.performance_metrics["function_calls"][func_name],
                    "avg_time": sum(times) / len(times),
                    "max_time": max(times),
                    "min_time": min(times),
                    "total_time": sum(times),
                }

        return report