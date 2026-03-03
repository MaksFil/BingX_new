import aiosqlite
import asyncio
import logging
from contextlib import asynccontextmanager

class ConnectionPool:
    """Пул соединений для БД"""

    def __init__(self, db_path: str, pool_size: int = 5):
        self.db_path = db_path
        self.pool_size = pool_size
        self._pool: asyncio.Queue = asyncio.Queue(maxsize=pool_size)
        self._initialized = False

    async def initialize(self):
        if self._initialized:
            return
        for _ in range(self.pool_size):
            conn = await aiosqlite.connect(self.db_path, timeout=30.0)
            await conn.execute("PRAGMA journal_mode=WAL")
            await self._pool.put(conn)
        self._initialized = True
        logging.info(f"✅ Connection pool initialized with {self.pool_size} connections")

    @asynccontextmanager
    async def acquire(self):
        if not self._initialized:
            await self.initialize()
        conn = await self._pool.get()
        try:
            yield conn
        finally:
            await self._pool.put(conn)

    async def close_all(self):
        while not self._pool.empty():
            conn = await self._pool.get()
            await conn.close()
        self._initialized = False
        logging.info("🔒 All connections closed")
