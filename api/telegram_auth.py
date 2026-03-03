import logging
from telethon import TelegramClient
from telethon.errors import (
    SessionPasswordNeededError,
    FloodWaitError,
)

class TelegramAuthManager:
    def __init__(self):
        self.client = None
        self.api_id = None
        self.api_hash = None
        self.phone = None
        self.code_hash = None
        self.connected = False

    async def send_code(self, api_id: int, api_hash: str, phone: str):
        try:
            self.api_id = api_id
            self.api_hash = api_hash
            self.phone = phone

            self.client = TelegramClient(
                "trading_bot_session",
                api_id,
                api_hash,
            )

            await self.client.connect()

            result = await self.client.send_code_request(phone)
            self.code_hash = result.phone_code_hash

            return {"status": "code_sent"}

        except FloodWaitError as e:
            raise Exception(f"Подождите {e.seconds} секунд")
        except Exception as e:
            logging.error(e)
            raise

    async def verify(self, code: str, password: str | None = None):
        try:
            if not self.client:
                raise Exception("Клиент не инициализирован")

            try:
                await self.client.sign_in(
                    phone=self.phone,
                    code=code,
                    phone_code_hash=self.code_hash
                )
            except SessionPasswordNeededError:
                if not password:
                    raise Exception("Требуется пароль 2FA")
                await self.client.sign_in(password=password)

            self.connected = True
            return {"status": "authorized"}

        except Exception as e:
            logging.error(e)
            raise

    async def get_status(self):
        if not self.client:
            return {"connected": False}

        if not await self.client.is_user_authorized():
            return {"connected": False}

        me = await self.client.get_me()
        return {
            "connected": True,
            "username": me.username,
            "first_name": me.first_name,
        }