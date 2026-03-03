import json
import logging
from collections import defaultdict
from typing import List

from fastapi import WebSocket


class WebSocketManager:
    """
    Централизованный менеджер WebSocket-соединений
    """

    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.event_handlers = defaultdict(list)

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        await self._trigger_event("connect", websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        dead_connections = []

        for connection in self.active_connections:
            try:
                await connection.send_text(json.dumps(message))
            except Exception:
                dead_connections.append(connection)

        for connection in dead_connections:
            self.disconnect(connection)
            await self._trigger_event("disconnect", connection, "broadcast_failed")

    # ---------------- EVENTS ----------------

    def add_event_handler(self, event_type: str, handler):
        """Регистрация обработчика событий"""
        self.event_handlers[event_type].append(handler)

    async def _trigger_event(self, event_type: str, *args, **kwargs):
        """Вызов зарегистрированных обработчиков"""
        for handler in self.event_handlers.get(event_type, []):
            await handler(*args, **kwargs)

    async def handle_message(self, websocket: WebSocket, message_text: str):
        try:
            message_data = json.loads(message_text)
            await self._trigger_event("message", message_data)
        except json.JSONDecodeError:
            logging.warning(f"Некорректное WS сообщение: {message_text}")
        except Exception as e:
            logging.error(f"Ошибка WS сообщения: {e}")

    async def notify(self, title: str, message: str, level: str = "info"):
        await self.broadcast(
            {
                "type": "notification",
                "title": title,
                "message": message,
                "level": level,
            }
        )


# Глобальный singleton
websocket_manager = WebSocketManager()
