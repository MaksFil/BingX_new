"""
Система кешування для оптимізації продуктивності бота
"""
from typing import Any, Optional, Callable, TypeVar, Generic
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import wraps
from collections import OrderedDict
import asyncio
import hashlib
import json
import logging


T = TypeVar('T')


@dataclass
class CacheEntry(Generic[T]):
    """Запис в кеші"""
    value: T
    timestamp: datetime
    ttl: float  # Time to live в секундах
    hits: int = 0
    
    def is_expired(self) -> bool:
        """Перевірка чи запис застарів"""
        age = (datetime.now() - self.timestamp).total_seconds()
        return age > self.ttl
    
    def increment_hits(self):
        """Збільшення лічильника звернень"""
        self.hits += 1


class LRUCache:
    """Least Recently Used Cache з автоматичним видаленням"""
    
    def __init__(self, max_size: int = 1000):
        self.max_size = max_size
        self.cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self.stats = {
            'hits': 0,
            'misses': 0,
            'evictions': 0,
            'expired': 0
        }
    
    def get(self, key: str) -> Optional[Any]:
        """Отримання значення з кешу"""
        if key not in self.cache:
            self.stats['misses'] += 1
            return None
        
        entry = self.cache[key]
        
        # Перевірка терміну дії
        if entry.is_expired():
            del self.cache[key]
            self.stats['expired'] += 1
            self.stats['misses'] += 1
            return None
        
        # Переміщення в кінець (найчастіше використовується)
        self.cache.move_to_end(key)
        entry.increment_hits()
        self.stats['hits'] += 1
        
        return entry.value
    
    def set(self, key: str, value: Any, ttl: float = 300):
        """Додавання значення в кеш"""
        # Видалення старого запису якщо існує
        if key in self.cache:
            del self.cache[key]
        
        # Видалення найстарішого якщо досягнуто ліміту
        if len(self.cache) >= self.max_size:
            oldest_key = next(iter(self.cache))
            del self.cache[oldest_key]
            self.stats['evictions'] += 1
        
        # Додавання нового запису
        entry = CacheEntry(
            value=value,
            timestamp=datetime.now(),
            ttl=ttl
        )
        self.cache[key] = entry
    
    def delete(self, key: str):
        """Видалення запису"""
        if key in self.cache:
            del self.cache[key]
    
    def clear(self):
        """Очищення всього кешу"""
        self.cache.clear()
        logging.info("🗑️ Cache cleared")
    
    def cleanup_expired(self):
        """Видалення застарілих записів"""
        expired_keys = [
            key for key, entry in self.cache.items()
            if entry.is_expired()
        ]
        
        for key in expired_keys:
            del self.cache[key]
            self.stats['expired'] += 1
        
        if expired_keys:
            logging.debug(f"🗑️ Removed {len(expired_keys)} expired cache entries")
    
    def get_stats(self) -> dict:
        """Статистика кешу"""
        total_requests = self.stats['hits'] + self.stats['misses']
        hit_rate = (self.stats['hits'] / total_requests * 100) if total_requests > 0 else 0
        
        return {
            'size': len(self.cache),
            'max_size': self.max_size,
            'hits': self.stats['hits'],
            'misses': self.stats['misses'],
            'hit_rate_percent': round(hit_rate, 2),
            'evictions': self.stats['evictions'],
            'expired': self.stats['expired']
        }


class SmartCache:
    """Розумний кеш з різними стратегіями"""
    
    def __init__(self):
        # Різні кеші для різних типів даних
        self.price_cache = LRUCache(max_size=500)        # Ціни
        self.market_cache = LRUCache(max_size=200)       # Інформація про ринки
        self.balance_cache = LRUCache(max_size=10)       # Баланси
        self.ticker_cache = LRUCache(max_size=100)       # Тікери
        
        # TTL для різних типів
        self.ttls = {
            'price': 5,      # 5 секунд
            'market': 3600,  # 1 година
            'balance': 30,   # 30 секунд
            'ticker': 10     # 10 секунд
        }
        
        # Задача для періодичного очищення
        self.cleanup_task: Optional[asyncio.Task] = None
    
    def start_cleanup_loop(self, interval: int = 60):
        """Запуск періодичного очищення"""
        async def cleanup_loop():
            while True:
                try:
                    await asyncio.sleep(interval)
                    self.cleanup_all()
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logging.error(f"Error in cleanup loop: {e}")
        
        self.cleanup_task = asyncio.create_task(cleanup_loop())
        logging.info("✅ Cache cleanup loop started")
    
    def stop_cleanup_loop(self):
        """Зупинка очищення"""
        if self.cleanup_task and not self.cleanup_task.done():
            self.cleanup_task.cancel()
    
    def get_price(self, symbol: str) -> Optional[float]:
        """Отримання ціни з кешу"""
        key = f"price:{symbol}"
        return self.price_cache.get(key)
    
    def set_price(self, symbol: str, price: float):
        """Збереження ціни в кеш"""
        key = f"price:{symbol}"
        self.price_cache.set(key, price, ttl=self.ttls['price'])
    
    def get_market_info(self, symbol: str) -> Optional[dict]:
        """Отримання інформації про ринок"""
        key = f"market:{symbol}"
        return self.market_cache.get(key)
    
    def set_market_info(self, symbol: str, info: dict):
        """Збереження інформації про ринок"""
        key = f"market:{symbol}"
        self.market_cache.set(key, info, ttl=self.ttls['market'])
    
    def get_balance(self, currency: str = 'USDT') -> Optional[float]:
        """Отримання балансу"""
        key = f"balance:{currency}"
        return self.balance_cache.get(key)
    
    def set_balance(self, balance: float, currency: str = 'USDT'):
        """Збереження балансу"""
        key = f"balance:{currency}"
        self.balance_cache.set(key, balance, ttl=self.ttls['balance'])
    
    def cleanup_all(self):
        """Очищення всіх кешів від застарілих записів"""
        self.price_cache.cleanup_expired()
        self.market_cache.cleanup_expired()
        self.balance_cache.cleanup_expired()
        self.ticker_cache.cleanup_expired()
    
    def clear_all(self):
        """Повне очищення всіх кешів"""
        self.price_cache.clear()
        self.market_cache.clear()
        self.balance_cache.clear()
        self.ticker_cache.clear()
        logging.info("🗑️ All caches cleared")
    
    def get_all_stats(self) -> dict:
        """Загальна статистика всіх кешів"""
        return {
            'price_cache': self.price_cache.get_stats(),
            'market_cache': self.market_cache.get_stats(),
            'balance_cache': self.balance_cache.get_stats(),
            'ticker_cache': self.ticker_cache.get_stats()
        }

_global_caches = {}

def cached(cache_key: str, ttl: float = 300):
    """Декоратор для кешування результатів функції зі збором статистики"""

    def decorator(func: Callable) -> Callable:
        # Створюємо кеш для конкретної функції, якщо його ще немає
        if cache_key not in _global_caches:
            _global_caches[cache_key] = LRUCache(max_size=100)
            logging.info(f"✨ Created new global cache instance: '{cache_key}'")

        # Використовуємо кеш з глобального словника
        cache = _global_caches[cache_key]

        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            # Генерація ключа
            key_parts = [cache_key, str(args), str(kwargs)]
            key = hashlib.md5('|'.join(key_parts).encode()).hexdigest()

            # Перевірка кешу
            cached_value = cache.get(key)
            if cached_value is not None:
                logging.debug(f"📦 Cache HIT: {func.__name__}")
                return cached_value

            # Виклик функції
            logging.debug(f"🔄 Cache MISS: {func.__name__}")
            result = await func(*args, **kwargs)

            # Збереження в кеш
            cache.set(key, result, ttl=ttl)

            return result

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            # Генерація ключа
            key_parts = [cache_key, str(args), str(kwargs)]
            key = hashlib.md5('|'.join(key_parts).encode()).hexdigest()

            # Перевірка кешу
            cached_value = cache.get(key)
            if cached_value is not None:
                logging.debug(f"📦 Cache HIT: {func.__name__}")
                return cached_value

            # Виклик функції
            logging.debug(f"🔄 Cache MISS: {func.__name__}")
            result = func(*args, **kwargs)

            # Збереження в кеш
            cache.set(key, result, ttl=ttl)

            return result

        # Визначення чи функція асинхронна
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper

    return decorator


class RateLimiter:
    """Rate limiter для запобігання перевищення ліміту запитів"""
    
    def __init__(self, max_calls: int, time_window: float):
        """
        Args:
            max_calls: Максимальна кількість викликів
            time_window: Часове вікно в секундах
        """
        self.max_calls = max_calls
        self.time_window = time_window
        self.calls: list[datetime] = []
        self.lock = asyncio.Lock()
    
    async def acquire(self):
        """Очікування дозволу на виконання"""
        async with self.lock:
            now = datetime.now()
            
            # Видалення старих викликів
            cutoff = now - timedelta(seconds=self.time_window)
            self.calls = [call for call in self.calls if call > cutoff]
            
            # Якщо досягнуто ліміту - очікування
            if len(self.calls) >= self.max_calls:
                oldest_call = self.calls[0]
                wait_time = (oldest_call + timedelta(seconds=self.time_window) - now).total_seconds()
                
                if wait_time > 0:
                    logging.debug(f"⏳ Rate limit reached, waiting {wait_time:.2f}s")
                    await asyncio.sleep(wait_time)
                    # Рекурсивний виклик після очікування
                    return await self.acquire()
            
            # Реєстрація виклику
            self.calls.append(now)
    
    def get_remaining_calls(self) -> int:
        """Кількість доступних викликів"""
        now = datetime.now()
        cutoff = now - timedelta(seconds=self.time_window)
        recent_calls = [call for call in self.calls if call > cutoff]
        return max(0, self.max_calls - len(recent_calls))


def rate_limited(max_calls: int, time_window: float):
    """Декоратор для обмеження частоти викликів"""
    
    def decorator(func: Callable) -> Callable:
        limiter = RateLimiter(max_calls, time_window)
        
        @wraps(func)
        async def wrapper(*args, **kwargs):
            await limiter.acquire()
            return await func(*args, **kwargs)
        
        return wrapper
    
    return decorator


# Приклад використання
async def example_usage():
    """Приклад використання системи кешування"""
    
    # 1. Використання SmartCache
    cache = SmartCache()
    cache.start_cleanup_loop(interval=30)
    
    # Збереження цін
    cache.set_price('BTC/USDT', 50000.0)
    cache.set_price('ETH/USDT', 3000.0)
    
    # Отримання з кешу
    btc_price = cache.get_price('BTC/USDT')
    print(f"BTC price from cache: {btc_price}")
    
    # Статистика
    stats = cache.get_all_stats()
    print(f"Cache stats: {json.dumps(stats, indent=2)}")
    
    # 2. Використання декоратора @cached
    @cached(cache_key='fetch_data', ttl=60)
    async def fetch_data(symbol: str):
        """Імітація запиту до API"""
        print(f"Fetching data for {symbol}...")
        await asyncio.sleep(1)  # Імітація затримки
        return {'symbol': symbol, 'price': 50000}
    
    # Перший виклик - пропустить кеш
    result1 = await fetch_data('BTC/USDT')
    print(f"First call: {result1}")
    
    # Другий виклик - з кешу
    result2 = await fetch_data('BTC/USDT')
    print(f"Second call (from cache): {result2}")
    
    # 3. Використання Rate Limiter
    @rate_limited(max_calls=5, time_window=10)
    async def limited_function():
        print(f"Called at {datetime.now()}")
        return "OK"
    
    # Виклики будуть обмежені
    for i in range(10):
        await limited_function()
    
    # Очищення
    cache.stop_cleanup_loop()


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    asyncio.run(example_usage())