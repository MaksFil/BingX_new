import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, Optional

import aiosqlite

from models.positions import Position
from core.safety.error_handlers import with_retry

UTC = timezone.utc


class ImprovedDatabaseManager:
    """
    Асинхронный менеджер БД с:
    - пулом соединений
    - авто-миграцией схемы
    - безопасным сохранением позиций
    """

    def __init__(self, db_path: str = "trading_bot.db", max_connections: int = 5):
        self.db_path = db_path
        self.lock = asyncio.Lock()

        self._connection_pool: Dict[int, aiosqlite.Connection] = {}
        self._pool: asyncio.Queue[aiosqlite.Connection] = asyncio.Queue(
            maxsize=max_connections
        )
        self._pool_initialized = False
        self.max_connections = max_connections

    # ------------------------------------------------------------------
    # CONNECTIONS
    # ------------------------------------------------------------------

    async def get_connection(self) -> aiosqlite.Connection:
        """Соединение, привязанное к asyncio task"""
        task_id = id(asyncio.current_task())
        if task_id not in self._connection_pool:
            self._connection_pool[task_id] = await aiosqlite.connect(
                self.db_path, timeout=30.0
            )
        return self._connection_pool[task_id]

    async def close_connections(self):
        """Закрытие всех соединений"""
        for conn in self._connection_pool.values():
            await conn.close()
        self._connection_pool.clear()

    @asynccontextmanager
    async def get_connection_pool(self):
        """Опциональный пул соединений"""
        if not self._pool_initialized:
            for _ in range(self.max_connections):
                conn = await aiosqlite.connect(self.db_path, timeout=30.0)
                await self._pool.put(conn)
            self._pool_initialized = True

        conn = await self._pool.get()
        try:
            yield conn
        finally:
            await self._pool.put(conn)

    # ------------------------------------------------------------------
    # INIT & MIGRATIONS
    # ------------------------------------------------------------------

    async def init_database(self):
        """Инициализация БД и проверка схемы"""
        async with self.lock:
            db = await self.get_connection()

            async with db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='positions'"
            ) as cursor:
                table_exists = await cursor.fetchone()

            if not table_exists:
                logging.info("🆕 Создание таблицы positions")
                await self._create_positions_table(db)
            else:
                await self._update_table_schema(db)

            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS config (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )

            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    position_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    action TEXT NOT NULL,
                    amount REAL NOT NULL,
                    price REAL NOT NULL,
                    pnl REAL,
                    timestamp TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            await db.commit()
            logging.info("✅ База данных инициализирована")

    async def _create_positions_table(self, db: aiosqlite.Connection):
        await db.execute(
            """
            CREATE TABLE positions (
                id TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                entry REAL NOT NULL,
                tp1 REAL,
                tp2 REAL,
                tp3 REAL,
                sl REAL NOT NULL,
                margin REAL NOT NULL,
                notional REAL NOT NULL,
                quantity REAL NOT NULL,
                leverage INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                remaining_amount REAL NOT NULL,
                tp1_hit INTEGER DEFAULT 0,
                trailing_active INTEGER DEFAULT 0,
                trailing_stop REAL,
                pnl REAL DEFAULT 0,
                pnl_percent REAL DEFAULT 0,
                auto_sl INTEGER DEFAULT 0,
                status TEXT DEFAULT 'open'
            )
            """
        )

    async def _update_table_schema(self, db: aiosqlite.Connection):
        async with db.execute("PRAGMA table_info(positions)") as cursor:
            columns_info = await cursor.fetchall()
            existing_columns = [col[1] for col in columns_info]

        required_columns = [
            ("tp2", "REAL"),
            ("tp3", "REAL"),
            ("remaining_amount", "REAL NOT NULL DEFAULT 0"),
            ("tp1_hit", "INTEGER DEFAULT 0"),
            ("trailing_active", "INTEGER DEFAULT 0"),
            ("trailing_stop", "REAL"),
            ("pnl", "REAL DEFAULT 0"),
            ("pnl_percent", "REAL DEFAULT 0"),
            ("auto_sl", "INTEGER DEFAULT 0"),
            ("status", "TEXT DEFAULT 'open'"),
        ]

        for name, col_type in required_columns:
            if name not in existing_columns:
                try:
                    await db.execute(
                        f"ALTER TABLE positions ADD COLUMN {name} {col_type}"
                    )
                    logging.info(f"➕ Добавлена колонка {name}")
                except Exception as e:
                    logging.warning(f"⚠️ Не удалось добавить {name}: {e}")

        await db.commit()

    # ------------------------------------------------------------------
    # POSITIONS
    # ------------------------------------------------------------------

    @with_retry(
        max_retries=3,
        component="database",
        retry_on=(aiosqlite.OperationalError,),
    )
    async def save_position_safe(self, position: Position) -> str:
        async with self.lock:
            db = await self.get_connection()

            def safe_float(value, default=0.0):
                try:
                    return float(value) if value is not None else default
                except Exception:
                    return default

            async with db.execute(
                "SELECT id FROM positions WHERE id = ?", (position.id,)
            ) as cursor:
                exists = await cursor.fetchone()

            if exists:
                await db.execute(
                    """
                    UPDATE positions SET
                        remaining_amount = ?,
                        pnl = ?,
                        pnl_percent = ?,
                        status = ?,
                        tp1_hit = ?,
                        trailing_active = ?,
                        trailing_stop = ?
                    WHERE id = ?
                    """,
                    (
                        safe_float(position.remaining_amount),
                        safe_float(position.pnl),
                        safe_float(position.pnl_percent),
                        position.status or "open",
                        int(position.tp1_hit or 0),
                        int(position.trailing_active or 0),
                        safe_float(position.trailing_stop),
                        position.id,
                    ),
                )
            else:
                await db.execute(
                    """
                    INSERT INTO positions VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )
                    """,
                    (
                        position.id,
                        position.symbol,
                        position.side,
                        safe_float(position.entry),
                        safe_float(position.tp1),
                        safe_float(position.tp2),
                        safe_float(position.tp3),
                        safe_float(position.sl),
                        safe_float(position.margin),
                        safe_float(position.notional),
                        safe_float(position.quantity),
                        position.leverage or 25,
                        (
                            position.timestamp.isoformat()
                            if position.timestamp
                            else datetime.now(UTC).isoformat()
                        ),
                        safe_float(position.remaining_amount),
                        int(position.tp1_hit or 0),
                        int(position.trailing_active or 0),
                        safe_float(position.trailing_stop),
                        safe_float(position.pnl),
                        safe_float(position.pnl_percent),
                        int(position.auto_sl or 0),
                        position.status or "open",
                    ),
                )

            await db.commit()
            return position.id

    async def update_position(self, position: Position):
        await self.save_position_safe(position)

    # ------------------------------------------------------------------
    # CONFIG
    # ------------------------------------------------------------------

    async def load_config(self) -> Dict[str, str]:
        async with self.lock:
            db = await self.get_connection()
            async with db.execute("SELECT key, value FROM config") as cursor:
                rows = await cursor.fetchall()
                return {k: v for k, v in rows}

    async def save_config(self, key: str, value: str):
        async with self.lock:
            db = await self.get_connection()
            await db.execute(
                "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
                (key, value),
            )
            await db.commit()

    # ------------------------------------------------------------------
    # TRADES
    # ------------------------------------------------------------------

    async def log_trade(
        self,
        position_id: str,
        symbol: str,
        side: str,
        action: str,
        amount: Decimal,
        price: Decimal,
        pnl: Optional[Decimal] = None,
    ):
        async with self.lock:
            db = await self.get_connection()
            await db.execute(
                """
                INSERT INTO trades (position_id, symbol, side, action, amount, price, pnl)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    position_id,
                    symbol,
                    side,
                    action,
                    float(amount),
                    float(price),
                    float(pnl) if pnl else None,
                ),
            )
            await db.commit()
