"""
Telethon userbot — слушает чужой канал и вызывает callback при новом посте.

Требует в .env:
  TG_API_ID    — с my.telegram.org
  TG_API_HASH  — с my.telegram.org
  SESSION_FILE — путь к файлу сессии (default: /root/tg_parser.session)
  SOURCE_CHANNELS — @channel1,@channel2  (откуда парсим)
"""

import os
from pathlib import Path
from telethon import TelegramClient, events
from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument

API_ID       = int(os.getenv("TG_API_ID", "0"))
API_HASH     = os.getenv("TG_API_HASH", "")
SESSION_FILE = os.getenv("SESSION_FILE", "/root/tg_parser.session")
SOURCE_CHANNELS = [
    c.strip() for c in os.getenv("SOURCE_CHANNELS", "").split(",") if c.strip()
]

_client: TelegramClient | None = None


def get_client() -> TelegramClient:
    global _client
    if _client is None:
        _client = TelegramClient(SESSION_FILE, API_ID, API_HASH)
    return _client


async def send_code(phone: str) -> str:
    client = get_client()
    await client.connect()
    result = await client.send_code_request(phone)
    return result.phone_code_hash


async def sign_in(phone: str, code: str, phone_code_hash: str) -> dict:
    client = get_client()
    await client.connect()
    try:
        await client.sign_in(phone, code, phone_code_hash=phone_code_hash)
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "reason": str(e)}


async def is_authorized() -> bool:
    if not API_ID or not API_HASH:
        return False
    try:
        client = get_client()
        await client.connect()
        return await client.is_user_authorized()
    except Exception:
        return False


async def start_listening(on_post) -> None:
    """Connect Telethon and fire on_post(text, source_channel) for every new message."""
    if not SOURCE_CHANNELS:
        raise ValueError("SOURCE_CHANNELS не задан в .env")

    client = get_client()
    await client.start()

    @client.on(events.NewMessage(chats=SOURCE_CHANNELS))
    async def handler(event):
        msg = event.message
        text: str = msg.text or msg.message or ""
        if not text.strip():
            return

        try:
            chat = await event.get_chat()
            source = f"@{getattr(chat, 'username', str(chat.id))}"
        except Exception:
            source = SOURCE_CHANNELS[0]

        await on_post(text=text, source=source, msg_id=msg.id)

    print(f"[PARSER] Telethon слушает: {SOURCE_CHANNELS}")
    await client.run_until_disconnected()
