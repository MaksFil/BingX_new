import asyncio
import logging
from datetime import datetime, UTC
from fastapi import WebSocket, WebSocketDisconnect

from api.websocket_manager import websocket_manager


def register_ws(app):

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        await websocket_manager.connect(websocket)

        await websocket.send_json({
            "type": "welcome",
            "timestamp": datetime.now(UTC).isoformat()
        })

        try:
            while True:
                try:
                    msg = await asyncio.wait_for(
                        websocket.receive_text(), timeout=60
                    )
                    await websocket_manager.handle_message(websocket, msg)

                except asyncio.TimeoutError:
                    await websocket.send_json({"type": "ping"})

        except WebSocketDisconnect:
            pass
        except Exception as e:
            logging.error(e)
        finally:
            websocket_manager.disconnect(websocket)
