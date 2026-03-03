"""
Покращена система обробки помилок з автоматичним відновленням
"""
from typing import Callable, Optional, Any
from functools import wraps
from enum import Enum
import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta


class ErrorSeverity(Enum):
    """Рівні серйозності помилок"""
    LOW = "low"          # Можна ігнорувати
    MEDIUM = "medium"    # Потребує логування
    HIGH = "high"        # Потребує повідомлення
    CRITICAL = "critical"  # Вимагає зупинки


@dataclass
class ErrorContext:
    """Контекст помилки для логування"""
    error: Exception
    severity: ErrorSeverity
    component: str
    action: str
    timestamp: datetime
    retry_count: int = 0
    metadata: dict = None


class RetryStrategy:
    """Стратегія повторних спроб"""
    
    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        exponential_base: float = 2.0
    ):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
    
    def get_delay(self, attempt: int) -> float:
        """Розрахунок затримки з експоненційним backoff"""
        delay = min(
            self.base_delay * (self.exponential_base ** attempt),
            self.max_delay
        )
        return delay


class CircuitBreaker:
    """Circuit breaker для запобігання каскадних помилок"""
    
    def __init__(
        self,
        failure_threshold: int = 5,
        timeout: float = 60.0,
        expected_exception: type = Exception
    ):
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.expected_exception = expected_exception
        
        self.failure_count = 0
        self.last_failure_time: Optional[datetime] = None
        self.state = "closed"  # closed, open, half_open
    
    def record_failure(self):
        """Реєстрація помилки"""
        self.failure_count += 1
        self.last_failure_time = datetime.now()
        
        if self.failure_count >= self.failure_threshold:
            self.state = "open"
            logging.warning(
                f"🔴 Circuit breaker OPENED after {self.failure_count} failures"
            )
    
    def record_success(self):
        """Реєстрація успішної операції"""
        self.failure_count = 0
        self.state = "closed"
        logging.info("✅ Circuit breaker CLOSED")
    
    def can_execute(self) -> bool:
        """Перевірка чи можна виконувати операцію"""
        if self.state == "closed":
            return True
        
        if self.state == "open":
            # Перевірка чи минув timeout
            if (datetime.now() - self.last_failure_time).seconds >= self.timeout:
                self.state = "half_open"
                logging.info("🟡 Circuit breaker HALF-OPEN")
                return True
            return False
        
        # half_open state
        return True


class SmartErrorHandler:
    """Розумна система обробки помилок"""
    
    def __init__(self):
        self.circuit_breakers: dict[str, CircuitBreaker] = {}
        self.error_history: list[ErrorContext] = []
        self.max_history = 1000
        
    def get_circuit_breaker(self, component: str) -> CircuitBreaker:
        """Отримання circuit breaker для компонента"""
        if component not in self.circuit_breakers:
            self.circuit_breakers[component] = CircuitBreaker()
        return self.circuit_breakers[component]
    
    def log_error(self, context: ErrorContext):
        """Логування помилки з контекстом"""
        self.error_history.append(context)
        if len(self.error_history) > self.max_history:
            self.error_history = self.error_history[-self.max_history:]
        
        log_msg = (
            f"[{context.severity.value.upper()}] "
            f"{context.component}.{context.action}: "
            f"{type(context.error).__name__}: {context.error}"
        )
        
        if context.severity == ErrorSeverity.CRITICAL:
            logging.critical(log_msg)
        elif context.severity == ErrorSeverity.HIGH:
            logging.error(log_msg)
        elif context.severity == ErrorSeverity.MEDIUM:
            logging.warning(log_msg)
        else:
            logging.info(log_msg)
    
    def get_error_stats(self, minutes: int = 60) -> dict:
        """Статистика помилок за період"""
        cutoff_time = datetime.now() - timedelta(minutes=minutes)
        recent_errors = [
            e for e in self.error_history 
            if e.timestamp >= cutoff_time
        ]
        
        by_severity = {}
        by_component = {}
        
        for error in recent_errors:
            # По серйозності
            severity = error.severity.value
            by_severity[severity] = by_severity.get(severity, 0) + 1
            
            # По компоненту
            component = error.component
            by_component[component] = by_component.get(component, 0) + 1
        
        return {
            'total_errors': len(recent_errors),
            'by_severity': by_severity,
            'by_component': by_component,
            'period_minutes': minutes
        }


def with_retry(
    max_retries: int = 3,
    retry_on: tuple = (Exception,),
    component: str = "unknown"
):
    """Декоратор для автоматичних повторних спроб"""
    
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            strategy = RetryStrategy(max_retries=max_retries)
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    result = await func(*args, **kwargs)
                    if attempt > 0:
                        logging.info(
                            f"✅ {component}.{func.__name__} succeeded on attempt {attempt + 1}"
                        )
                    return result
                    
                except retry_on as e:
                    last_exception = e
                    
                    if attempt < max_retries:
                        delay = strategy.get_delay(attempt)
                        logging.warning(
                            f"⚠️ {component}.{func.__name__} failed (attempt {attempt + 1}), "
                            f"retrying in {delay:.1f}s... Error: {e}"
                        )
                        await asyncio.sleep(delay)
                    else:
                        logging.error(
                            f"❌ {component}.{func.__name__} failed after {max_retries + 1} attempts"
                        )
            
            raise last_exception
        
        return wrapper
    return decorator


def with_circuit_breaker(component: str):
    """
    Декоратор з circuit breaker, який автоматично знаходить error_handler на екземплярі.
    Припускає, що декорований метод знаходиться в класі, у якого є атрибут 'error_handler'.
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(self, *args, **kwargs) -> Any:
            # 'self' тепер доступний тут, у момент виклику
            if not hasattr(self, 'error_handler') or not isinstance(self.error_handler, SmartErrorHandler):
                raise TypeError(f"Клас {self.__class__.__name__} повинен мати атрибут 'error_handler' типу SmartErrorHandler для використання цього декоратора.")

            error_handler = self.error_handler
            breaker = error_handler.get_circuit_breaker(component)

            if not breaker.can_execute():
                # Створюємо виняток, щоб його міг перехопити декоратор @with_retry
                raise Exception(f"Circuit breaker is OPEN for {component}")

            try:
                result = await func(self, *args, **kwargs)
                if breaker.state != "closed":
                    breaker.record_success()
                return result

            except Exception as e:
                breaker.record_failure()

                context = ErrorContext(
                    error=e,
                    severity=ErrorSeverity.HIGH,
                    component=component,
                    action=func.__name__,
                    timestamp=datetime.now()
                )
                error_handler.log_error(context)
                raise # Важливо прокинути виняток далі, щоб @with_retry міг його обробити

        return wrapper
    return decorator


# Приклад використання
async def example_usage():
    """Приклад використання системи обробки помилок"""
    
    error_handler = SmartErrorHandler()
    
    # Використання декораторів
    @with_retry(max_retries=3, component="exchange")
    @with_circuit_breaker("exchange", error_handler)
    async def fetch_price(symbol: str):
        """Приклад функції з обробкою помилок"""
        # Імітація можливої помилки
        import random
        if random.random() < 0.3:
            raise ConnectionError("API timeout")
        
        return {"symbol": symbol, "price": 50000}
    
    # Виклик функції
    try:
        for i in range(10):
            result = await fetch_price("BTC/USDT")
            print(f"Attempt {i+1}: {result}")
            await asyncio.sleep(1)
            
    except Exception as e:
        print(f"Final error: {e}")
    
    # Статистика
    stats = error_handler.get_error_stats(minutes=5)
    print(f"\nError statistics: {stats}")


if __name__ == "__main__":
    asyncio.run(example_usage())
