"""
Система кеширования и контроля лимитов запросов
"""
import asyncio
import hashlib
import logging
import json
from datetime import datetime, timedelta
from typing import Any, Optional, Callable, TypeVar, Generic, Dict, List
from dataclasses import dataclass, field
from functools import wraps
from collections import OrderedDict

T = TypeVar('T')
logger = logging.getLogger(__name__)

@dataclass
class CacheEntry(Generic[T]):
    value: T
    timestamp: datetime
    ttl: float
    hits: int = 0
    
    def is_expired(self) -> bool:
        return (datetime.now() - self.timestamp).total_seconds() > self.ttl

class LRUCache:
    """Оптимизированный LRU Cache"""
    def __init__(self, max_size: int = 1000):
        self.max_size = max_size
        self.cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self.lock = asyncio.Lock() # Для предотвращения коллизий в async
        self.stats = {'hits': 0, 'misses': 0, 'evictions': 0, 'expired': 0}
    
    async def get(self, key: str) -> Optional[Any]:
        async with self.lock:
            if key not in self.cache:
                self.stats['misses'] += 1
                return None
            
            entry = self.cache[key]
            if entry.is_expired():
                del self.cache[key]
                self.stats['expired'] += 1
                self.stats['misses'] += 1
                return None
            
            self.cache.move_to_end(key)
            entry.hits += 1
            self.stats['hits'] += 1
            return entry.value

    async def set(self, key: str, value: Any, ttl: float = 300):
        async with self.lock:
            if key in self.cache:
                del self.cache[key]
            
            if len(self.cache) >= self.max_size:
                self.cache.popitem(last=False) # Удаляем старейший (LRU)
                self.stats['evictions'] += 1
            
            self.cache[key] = CacheEntry(value=value, timestamp=datetime.now(), ttl=ttl)

    def cleanup_expired(self):
        """Синхронная очистка (вызывается из петли)"""
        now = datetime.now()
        expired = [k for k, v in self.cache.items() if (now - v.timestamp).total_seconds() > v.ttl]
        for k in expired:
            del self.cache[k]
            self.stats['expired'] += 1

class SmartCache:
    """Агрегатор кешей для разных типов данных бота"""
    def __init__(self):
        self.price_cache = LRUCache(max_size=500)
        self.market_cache = LRUCache(max_size=200)
        self.balance_cache = LRUCache(max_size=10)
        self.cleanup_task: Optional[asyncio.Task] = None
        
        self.ttls = {'price': 5, 'market': 3600, 'balance': 30}

    async def get_price(self, symbol: str) -> Optional[float]:
        return await self.price_cache.get(f"p:{symbol}")

    async def set_price(self, symbol: str, price: float):
        await self.price_cache.set(f"p:{symbol}", price, ttl=self.ttls['price'])

    def start_cleanup_loop(self, interval: int = 60):
        async def _loop():
            while True:
                try:
                    await asyncio.sleep(interval)
                    self.price_cache.cleanup_expired()
                    self.market_cache.cleanup_expired()
                except asyncio.CancelledError: break
                except Exception as e: logger.error(f"Cache Cleanup Error: {e}")
        self.cleanup_task = asyncio.create_task(_loop())

class RateLimiter:
    """Ограничитель частоты запросов с защитой от раздувания памяти"""
    def __init__(self, max_calls: int, time_window: float):
        self.max_calls = max_calls
        self.time_window = time_window
        self.calls: List[float] = [] # Храним только timestamp (float) для экономии памяти
        self.lock = asyncio.Lock()
    
    async def acquire(self):
        async with self.lock:
            now = datetime.now().timestamp()
            cutoff = now - self.time_window
            
            # Очищаем старые записи при каждом вызове
            self.calls = [c for c in self.calls if c > cutoff]
            
            if len(self.calls) >= self.max_calls:
                wait_time = self.calls[0] + self.time_window - now
                if wait_time > 0:
                    logger.warning(f"⏳ Rate limit! Waiting {wait_time:.2f}s")
                    await asyncio.sleep(wait_time)
                    return await self.acquire()
            
            self.calls.append(now)

# Глобальный реестр кешей для декоратора
_global_caches: Dict[str, LRUCache] = {}

def cached(cache_name: str, ttl: float = 300):
    """Декоратор для асинхронных функций"""
    if cache_name not in _global_caches:
        _global_caches[cache_name] = LRUCache(max_size=100)
    cache = _global_caches[cache_name]

    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Создаем компактный ключ
            raw_key = f"{func.__name__}:{args}:{kwargs}"
            key = hashlib.blake2b(raw_key.encode(), digest_size=16).hexdigest()
            
            val = await cache.get(key)
            if val is not None: return val
            
            res = await func(*args, **kwargs)
            await cache.set(key, res, ttl=ttl)
            return res
        return wrapper
    return decorator