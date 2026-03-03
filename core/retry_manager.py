import asyncio
import hashlib
import logging
import random
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set

# Импорт парсера сигналов
try:
    from utils.signal_parser import SignalParser, Signal
except ImportError:
    logging.warning("❌ signal_parser.py не найден. Класс SignalParser будет недоступен.")
    class Signal: pass
    class SignalParser:
        def parse_signal(self, text): return None


class RetryPriority(Enum):
    """Приоритеты для повторной обработки сигналов"""
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


@dataclass
class RetryableMessage:
    """Структура для хранения сообщения, которое нужно обработать повторно"""
    text: str
    metadata: Dict[str, Any]
    attempts: int = 0
    created_at: float = field(default_factory=time.time)
    priority: RetryPriority = RetryPriority.MEDIUM
    max_retries: int = 3
    backoff_multiplier: float = 1.5

    @property
    def next_retry_time(self) -> float:
        """Вычисляет время следующей попытки с экспоненциальной задержкой"""
        base_delay = 5.0  # базовая задержка в секундах
        delay = base_delay * (self.backoff_multiplier**self.attempts)
        jitter = random.uniform(0.8, 1.2)
        return self.created_at + (delay * jitter)

    @property
    def is_expired(self) -> bool:
        """Проверяет, истекло ли время жизни сообщения"""
        max_age = 3600  # 1 час
        return time.time() - self.created_at > max_age

    @property
    def age_seconds(self) -> float:
        """Возраст сообщения в секундах"""
        return time.time() - self.created_at


class SignalRetryManager:
    """
    Менеджер повторных попыток обработки сигналов с приоритетами, дедупликацией и аналитикой.
    """

    def __init__(
        self,
        max_queue_size: int = 200,
        cleanup_interval: int = 300,
        enable_analytics: bool = True,
        max_cache_size: int = 1000,
    ):
        self.max_queue_size = max_queue_size
        self.cleanup_interval = cleanup_interval
        self.enable_analytics = enable_analytics
        self.max_cache_size = max_cache_size

        # Очереди с приоритетами
        self.priority_queues: Dict[RetryPriority, deque] = {
            priority: deque() for priority in RetryPriority
        }

        # Аналитика
        self.stats = {
            "total_added": 0,
            "total_processed": 0,
            "successful_retries": 0,
            "failed_permanently": 0,
            "duplicate_detections": 0,
            "expired_messages": 0,
            "queue_overflows": 0,
        }

        # Кэш для дедупликации
        self.seen_messages: Set[str] = set()
        self.last_cleanup: Optional[int] = int(time.time())

        # Блокировка для потокобезопасности
        self._lock = asyncio.Lock()

        # Конфигурации по приоритетам
        self.priority_config = {
            RetryPriority.LOW: {"max_retries": 2, "backoff_multiplier": 2.0, "max_per_cycle": 1},
            RetryPriority.MEDIUM: {"max_retries": 3, "backoff_multiplier": 1.5, "max_per_cycle": 2},
            RetryPriority.HIGH: {"max_retries": 5, "backoff_multiplier": 1.2, "max_per_cycle": 3},
            RetryPriority.CRITICAL: {"max_retries": 7, "backoff_multiplier": 1.1, "max_per_cycle": 5},
        }

    def _hash_message(self, text: str, metadata: Dict) -> str:
        """Хеш для дедупликации"""
        content = f"{text}_{metadata.get('channel_id', '')}"
        return hashlib.md5(content.encode()).hexdigest()

    def _determine_priority(self, text: str, metadata: Dict) -> RetryPriority:
        """Определение приоритета по содержимому сообщения"""
        text_lower = text.lower()

        if any(coin in text_lower for coin in ["btc", "eth", "bnb"]):
            return RetryPriority.CRITICAL

        signal_keywords = ["entry", "tp", "sl", "long", "short"]
        keyword_count = sum(1 for kw in signal_keywords if kw in text_lower)
        if keyword_count >= 4:
            return RetryPriority.HIGH
        if keyword_count >= 2:
            return RetryPriority.MEDIUM
        return RetryPriority.LOW

    async def add_failed_message(
        self,
        text: str,
        metadata: Dict[str, Any],
        priority: Optional[RetryPriority] = None,
        max_retries: Optional[int] = None,
    ) -> bool:
        """Добавление сообщения в очередь повторных попыток"""
        async with self._lock:
            msg_hash = self._hash_message(text, metadata)
            if msg_hash in self.seen_messages:
                self.stats["duplicate_detections"] += 1
                logging.debug(f"Дубликат сообщения: {text[:30]}...")
                return False

            if priority is None:
                priority = self._determine_priority(text, metadata)

            config = self.priority_config[priority]
            if max_retries is None:
                max_retries = int(config["max_retries"])

            total_messages = sum(len(q) for q in self.priority_queues.values())
            if total_messages >= self.max_queue_size:
                cleaned = self._cleanup_old_messages(force=True)
                if cleaned == 0:
                    self.stats["queue_overflows"] += 1
                    logging.warning(f"Очередь переполнена, сообщение отклонено: {text[:50]}...")
                    return False

            retry_message = RetryableMessage(
                text=text,
                metadata=metadata,
                priority=priority,
                max_retries=max_retries,
                backoff_multiplier=config["backoff_multiplier"],
            )

            self.priority_queues[priority].append(retry_message)
            self.seen_messages.add(msg_hash)
            self.stats["total_added"] += 1

            logging.info(f"Сообщение добавлено в очередь {priority.name} (попыток: {max_retries}): {text[:50]}...")
            return True

    async def process_retries(self, parser: SignalParser) -> Optional[Signal]:
        """Обработка очереди повторных попыток"""
        async with self._lock:
            await self._periodic_cleanup()

            for priority in sorted(RetryPriority, key=lambda x: x.value, reverse=True):
                queue = self.priority_queues[priority]
                config = self.priority_config[priority]

                processed_count = 0
                max_per_cycle = config["max_per_cycle"]
                messages_to_requeue = []

                while queue and processed_count < max_per_cycle:
                    message = queue.popleft()

                    if message.is_expired:
                        self.stats["expired_messages"] += 1
                        logging.warning(f"Сообщение истекло ({message.age_seconds:.1f}s): {message.text[:50]}...")
                        continue

                    if time.time() < message.next_retry_time:
                        messages_to_requeue.append(message)
                        continue

                    message.attempts += 1
                    self.stats["total_processed"] += 1

                    try:
                        logging.info(f"Повторная попытка парсинга {message.attempts}/{message.max_retries} (приоритет {priority.name})")
                        signal = parser.parse_signal(message.text)
                        if signal:
                            self.stats["successful_retries"] += 1
                            logging.info(f"Успешный парсинг: {signal.symbol} (попытка {message.attempts})")
                            for msg in messages_to_requeue:
                                queue.appendleft(msg)
                            return signal
                        else:
                            if message.attempts >= message.max_retries:
                                self.stats["failed_permanently"] += 1
                                logging.warning(f"Превышено количество попыток (приоритет {priority.name}): {message.text[:50]}...")
                            else:
                                messages_to_requeue.append(message)
                    except Exception as e:
                        logging.error(f"Ошибка при повторной обработке: {e}")
                        if message.attempts < message.max_retries:
                            messages_to_requeue.append(message)

                    processed_count += 1

                for message in reversed(messages_to_requeue):
                    queue.appendleft(message)

                if processed_count > 0:
                    break

            return None

    async def _periodic_cleanup(self):
        now = time.time()
        if self.last_cleanup is not None and now - self.last_cleanup > self.cleanup_interval:
            self._cleanup_old_messages()
            self._cleanup_seen_cache()
            self.last_cleanup = int(now)

    def _cleanup_old_messages(self, force: bool = False) -> int:
        removed_count = 0
        for priority, queue in self.priority_queues.items():
            if force and priority == RetryPriority.LOW:
                removed_count += len(queue)
                queue.clear()
            else:
                messages_to_keep = []
                for message in queue:
                    if message.is_expired or message.attempts >= message.max_retries:
                        removed_count += 1
                    else:
                        messages_to_keep.append(message)
                queue.clear()
                queue.extend(messages_to_keep)

        if removed_count > 0:
            logging.info(f"Очищено {removed_count} устаревших сообщений из очереди")
        return removed_count

    def _cleanup_seen_cache(self):
        if len(self.seen_messages) > self.max_cache_size:
            messages_to_keep = random.sample(list(self.seen_messages), self.max_cache_size // 2)
            self.seen_messages = set(messages_to_keep)
            logging.info(f"Очищен кэш дедупликации: оставлено {len(messages_to_keep)} записей")

    def get_analytics(self) -> Dict[str, Any]:
        if not self.enable_analytics:
            return {}
        queue_sizes = {}
        queue_details = {}

        for priority, queue in self.priority_queues.items():
            queue_sizes[priority.name] = len(queue)
            if queue:
                ages = [msg.age_seconds for msg in queue]
                attempts = [msg.attempts for msg in queue]
                queue_details[priority.name] = {
                    "size": len(queue),
                    "avg_age_seconds": sum(ages) / len(ages),
                    "max_age_seconds": max(ages),
                    "avg_attempts": sum(attempts) / len(attempts),
                    "max_attempts": max(attempts),
                    "ready_for_retry": sum(1 for msg in queue if time.time() >= msg.next_retry_time),
                }

        success_rate = 0
        if self.stats["total_processed"] > 0:
            success_rate = (self.stats["successful_retries"] / self.stats["total_processed"]) * 100

        return {
            "queue_sizes": queue_sizes,
            "total_queued": sum(queue_sizes.values()),
            "queue_details": queue_details,
            "stats": self.stats.copy(),
            "success_rate_percent": round(success_rate, 2),
            "cache_size": len(self.seen_messages),
            "last_cleanup": self.last_cleanup,
            "next_cleanup": self.last_cleanup + self.cleanup_interval if self.last_cleanup else 0,
            "configuration": {
                "max_queue_size": self.max_queue_size,
                "cleanup_interval": self.cleanup_interval,
                "max_cache_size": self.max_cache_size,
                "priority_config": {p.name: cfg for p, cfg in self.priority_config.items()},
            },
        }

    def clear_all_queues(self):
        total_cleared = sum(len(q) for q in self.priority_queues.values())
        for q in self.priority_queues.values():
            q.clear()
        self.seen_messages.clear()
        logging.info(f"Очищены все очереди: удалено {total_cleared} сообщений")
        return total_cleared

    async def get_queue_sample(self, priority: RetryPriority, limit: int = 5) -> List[Dict]:
        async with self._lock:
            queue = self.priority_queues[priority]
            sample = []
            for i, message in enumerate(queue):
                if i >= limit:
                    break
                sample.append({
                    "text_preview": message.text[:100],
                    "attempts": message.attempts,
                    "age_seconds": message.age_seconds,
                    "next_retry_in": max(0, message.next_retry_time - time.time()),
                    "priority": message.priority.name,
                    "metadata": message.metadata,
                })
            return sample
