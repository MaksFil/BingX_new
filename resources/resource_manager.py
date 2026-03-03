import aiosqlite
import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Optional
from core.modes.demo_trading import DemoExchange

class ResourceManager:
    """Централізоване управління всіма ресурсами бота"""

    def __init__(self):
        self.db_connection: Optional[aiosqlite.Connection] = None
        self.exchange_client = None
        self.telegram_client = None
        self.cleanup_tasks: list = []

    @asynccontextmanager
    async def manage_database(self, db_path: str):
        """Context manager для БД з автоматичним закриттям"""
        connection = None
        try:
            connection = await aiosqlite.connect(
                db_path,
                timeout=30.0,
                isolation_level=None  # autocommit mode
            )
            # Оптимізація SQLite
            await connection.execute("PRAGMA journal_mode=WAL")
            await connection.execute("PRAGMA synchronous=NORMAL")
            await connection.execute("PRAGMA cache_size=-64000")  # 64MB cache
            await connection.execute("PRAGMA temp_store=MEMORY")

            self.db_connection = connection
            logging.info("✅ Database connection established")
            yield connection

        except Exception as e:
            logging.error(f"❌ Database error: {e}")
            raise
        finally:
            if connection:
                await connection.close()
                logging.info("🔒 Database connection closed")
                

    @asynccontextmanager
    async def manage_exchange(self, exchange_config: dict):
        """Context manager для біржі с поддержкой демо-режима"""
        import ccxt.pro as ccxt

        exchange = None

        # Определяем, демо ли режим (пустые ключи или явно demo)
        is_demo = (
            exchange_config.get('api_key') in (None, '', 'demo') or
            exchange_config.get('api_secret') in (None, '', 'demo')
        )

        try:
            if is_demo:
                # Создаём фиктивную биржу
                exchange = DemoExchange(exchange_config.get('name', 'demo'))
                yield exchange
            else:
                exchange_class = getattr(ccxt, exchange_config['name'])
                exchange = exchange_class({
                    'apiKey': exchange_config['api_key'],
                    'secret': exchange_config['api_secret'],
                    'enableRateLimit': True,
                    'options': {
                        'defaultType': 'swap',
                        'adjustForTimeDifference': True
                    }
                })

                # Проверка подключения
                await exchange.load_markets()
                self.exchange_client = exchange
                logging.info(f"✅ Exchange {exchange_config['name']} connected")
                yield exchange

        except Exception as e:
            logging.error(f"❌ Exchange connection error: {e}")
            raise
        finally:
            if exchange:
                await exchange.close()
                logging.info("🔒 Exchange connection closed")

    async def cleanup(self):
        """Очищення всіх ресурсів"""
        logging.info("🧹 Starting cleanup...")

        # Скасування задач
        for task in self.cleanup_tasks:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        # Закриття з'єднань
        if self.exchange_client:
            await self.exchange_client.close()

        if self.telegram_client:
            await self.telegram_client.disconnect()

        if self.db_connection:
            await self.db_connection.close()

        logging.info("✅ Cleanup completed")
