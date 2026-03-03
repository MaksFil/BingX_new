import os
import sys
import logging
import warnings
import asyncio
import signal
import traceback

import uvicorn
from fastapi import FastAPI

from api.interface import WebInterface  
from core.bot import AdvancedTradingBot, signal_handler

app = FastAPI(title="Advanced Trading Bot v2.1", version="2.1.0")

async def main():
    """Главная функция запуска бота с комплексной обработкой ошибок"""

    # Настройка глобальной обработки ошибок
    def setup_error_handling():
        """Настройка глобальной обработки ошибок"""

        def handle_exception(exc_type, exc_value, exc_traceback):
            """Глобальный обработчик необработанных исключений"""
            if issubclass(exc_type, KeyboardInterrupt):
                # Позволяем KeyboardInterrupt проходить
                sys.__excepthook__(exc_type, exc_value, exc_traceback)
                return

            logging.error(
                "Необработанное исключение",
                exc_info=(exc_type, exc_value, exc_traceback),
            )

        sys.excepthook = handle_exception

    setup_error_handling()

    # Подавление предупреждений
    warnings.filterwarnings("ignore", category=UserWarning)
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    warnings.filterwarnings("ignore", category=RuntimeWarning)

    # Специальные настройки для библиотек
    logging.getLogger("telethon").setLevel(logging.ERROR)
    logging.getLogger("telethon.network").setLevel(logging.CRITICAL)
    logging.getLogger("telethon.client").setLevel(logging.ERROR)
    logging.getLogger("telethon.extensions").setLevel(logging.ERROR)

    # Windows-специфичные настройки
    if os.name == "nt":
        logging.getLogger("asyncio").setLevel(logging.ERROR)
        logging.getLogger("asyncio.proactor_events").setLevel(logging.CRITICAL)
        logging.getLogger("asyncio.base_events").setLevel(logging.ERROR)

    # Настройка основного логирования
    class SmartFilter(logging.Filter):
        """Умный фильтр для подавления спама"""

        def __init__(self):
            super().__init__()
            self.spam_patterns = [
                "very old message",
                "Server sent a very old message",
                "Connection closed while receiving",
                "ConnectionAbortedError",
                "WinError 10054",
                "WinError 10053",
                "call_connection_lost",
                "разорвал установленное подключение",
                "разорвала установленное подключение",
                "Connection lost",
                "ProactorBasePipeTransport",
                "The server closed the connection",
            ]
            self.last_messages = {}

        def filter(self, record):
            message = record.getMessage()

            # Подавляем известные спам-сообщения
            if any(pattern in message for pattern in self.spam_patterns):
                return False

            # Подавляем повторяющиеся HTTP запросы
            if "GET /api/" in message and "200 OK" in message:
                # Разрешаем только каждое 10-е сообщение такого типа
                key = "api_requests"
                self.last_messages[key] = self.last_messages.get(key, 0) + 1
                return self.last_messages[key] % 10 == 0

            return True

    # Настройка логирования с улучшенным фильтром
    root_logger = logging.getLogger()

    # Создаем форматтер
    formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(message)s", datefmt="%H:%M:%S"
    )

    # Файловый хендлер
    try:
        file_handler = logging.FileHandler("trading_bot.log", encoding="utf-8")
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(formatter)
        file_handler.addFilter(SmartFilter())
    except Exception as e:
        print(f"Не удалось создать файл лога: {e}")
        file_handler = None

    # Консольный хендлер
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    console_handler.addFilter(SmartFilter())

    # Настраиваем root logger
    root_logger.setLevel(logging.DEBUG)
    root_logger.handlers.clear()
    if file_handler:
        root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    # Настройка логирования для веб-сервера
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.ERROR)
    logging.getLogger("uvicorn.error").setLevel(logging.ERROR)

    # Регистрация обработчиков сигналов
    signal.signal(signal.SIGINT, signal_handler)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, signal_handler)

    # Создание и инициализация бота
    bot = None
    server = None

    try:
        logging.info("=" * 60)
        logging.info("🚀 Запуск Advanced Trading Bot v2.1 с WebSocket")
        logging.info("📡 Real-time обновления через WebSocket")
        logging.info("🔧 Улучшенная обработка ошибок Telegram")
        logging.info("=" * 60)

        bot = AdvancedTradingBot()

        # Инициализация бота с обработкой ошибок
        init_success = await bot.initialize()
        await bot.initialize_telegram()
        if not init_success:
            logging.warning("Бот запущен с ограниченной функциональностью")

        # Настройка веб-сервера
        config = uvicorn.Config(
            app,
            host="0.0.0.0",
            port=8000,
            log_level="error",  # Минимальные логи
            access_log=False,  # Без access логов
            server_header=False,  # Без server header
            date_header=False,  # Без date header
            use_colors=False,  # Без цветов в логах
        )
        server = uvicorn.Server(config)

        # Установка обработчика asyncio исключений
        loop = asyncio.get_running_loop()
        loop.set_exception_handler(lambda loop, context: None)  # Тихий режим

        logging.info("🌐 Веб-интерфейс: http://localhost:8000")
        logging.info("⚡ WebSocket: ws://localhost:8080/ws")
        logging.info("ℹ️  Для остановки нажмите Ctrl+C")
        logging.info("-" * 40)

        # Запуск основных задач
        tasks = [
            asyncio.create_task(bot.run_main_loop(), name="bot_main_loop"),
            asyncio.create_task(server.serve(), name="web_server"),
        ]

        # Ожидание завершения с обработкой исключений
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

        # Отменяем оставшиеся задачи
        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    except KeyboardInterrupt:
        logging.info("🛑 Получен сигнал остановки (Ctrl+C)")
    except SystemExit:
        logging.info("🛑 Системный выход")
    except Exception as e:
        error_msg = str(e)[:200]
        logging.error(f"❌ Критическая ошибка: {error_msg}")

        # Не показываем полный трейсбек в продакшене
        if logging.getLogger().level <= logging.DEBUG:
            logging.error(f"Детали ошибки: {traceback.format_exc()}")
    finally:
        # Корректное завершение
        logging.info("🔄 Завершение работы...")

        # Останавливаем бота
        if bot and hasattr(bot, "graceful_shutdown"):
            # try:
                await asyncio.wait_for(bot.graceful_shutdown(), timeout=30.0)
            # except asyncio.TimeoutError:
            #     logging.warning("Таймаут при завершении работы бота")
            # except Exception as e:
            #     logging.error(f"Ошибка при завершении бота: {e}")

        # Останавливаем сервер
        if server and hasattr(server, "should_exit"):
            try:
                server.should_exit = True
                if hasattr(server, "force_exit"):
                    server.force_exit = True
            except Exception as e:
                logging.debug(f"Ошибка остановки сервера: {e}")

        logging.info("✅ Работа завершена")


if __name__ == "__main__":
    # try:
        # Установка политики событий для Windows
        if os.name == "nt":
            try:
                # Используем ProactorEventLoop для Windows
                asyncio.set_event_loop_policy(
                    asyncio.WindowsProactorEventLoopPolicy())
            except AttributeError:
                # Fallback для старых версий Python
                pass

        # Запуск с обработкой ошибок
        asyncio.run(main())

    # except KeyboardInterrupt:
    #     print("\n🛑 Прервано пользователем")
    # except Exception as e:
    #     print(f"\n❌ Критическая ошибка запуска: {e}")
    # finally:
    #     print("👋 До свидания!")
    #     # Небольшая пауза перед закрытием окна
    #     try:
    #         if os.name == "nt":  # Windows
    #             time.sleep(1)
    #     except BaseException:
    #         pass


# # Создаём FastAPI
# app = FastAPI()

# # Создаём бота
# bot = AdvancedTradingBot()

# # Регистрируем веб-интерфейс
# WebInterface(app, bot)

# if __name__ == "__main__":
#     uvicorn.run(
#         "main:app",
#         host="0.0.0.0",
#         port=8000,
#         reload=True
#     )