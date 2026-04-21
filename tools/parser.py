import os
import asyncio
from pathlib import Path
from datetime import datetime
from telethon import TelegramClient, events
from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument

API_ID = int(os.getenv("TG_API_ID", "0"))
API_HASH = os.getenv("TG_API_HASH", "")
SESSION_FILE = os.getenv("SESSION_FILE", "/root/tg_parser.session")
MEDIA_DIR = Path(os.getenv("MEDIA_DIR", "/root/crossposting/media"))
MEDIA_DIR.mkdir(parents=True, exist_ok=True)

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
    client = get_client()
    await client.connect()
    return await client.is_user_authorized()


async def parse_channel(channel: str, limit: int = 50, download_media: bool = True) -> list[dict]:
    client = get_client()
    await client.connect()

    messages = []
    async for msg in client.iter_messages(channel, limit=limit):
        item = {
            "id": msg.id,
            "channel": channel,
            "text": msg.text or msg.message or "",
            "date": msg.date.isoformat() if msg.date else "",
            "views": getattr(msg, "views", 0) or 0,
            "media_type": None,
            "media_path": None,
        }

        if msg.media and download_media:
            media_folder = MEDIA_DIR / channel.lstrip("@")
            media_folder.mkdir(parents=True, exist_ok=True)

            if isinstance(msg.media, MessageMediaPhoto):
                item["media_type"] = "photo"
                path = await client.download_media(msg.media, str(media_folder / f"{msg.id}.jpg"))
                item["media_path"] = str(path) if path else None
            elif isinstance(msg.media, MessageMediaDocument):
                doc = msg.media.document
                mime = getattr(doc, "mime_type", "")
                if mime.startswith("video"):
                    item["media_type"] = "video"
                    path = await client.download_media(msg.media, str(media_folder / f"{msg.id}.mp4"))
                    item["media_path"] = str(path) if path else None

        messages.append(item)

    return messages


_realtime_handlers: dict[str, object] = {}


async def start_realtime(channels: list[str], on_message) -> None:
    client = get_client()
    await client.connect()

    @client.on(events.NewMessage(chats=channels))
    async def handler(event):
        msg = event.message
        channel = ""
        try:
            chat = await event.get_chat()
            channel = f"@{getattr(chat, 'username', str(chat.id))}"
        except Exception:
            pass

        item = {
            "id": msg.id,
            "channel": channel,
            "text": msg.text or msg.message or "",
            "date": msg.date.isoformat() if msg.date else "",
            "views": getattr(msg, "views", 0) or 0,
            "media_type": None,
            "media_path": None,
        }

        if msg.media:
            media_folder = MEDIA_DIR / channel.lstrip("@")
            media_folder.mkdir(parents=True, exist_ok=True)

            if isinstance(msg.media, MessageMediaPhoto):
                item["media_type"] = "photo"
                path = await client.download_media(msg.media, str(media_folder / f"{msg.id}.jpg"))
                item["media_path"] = str(path) if path else None
            elif isinstance(msg.media, MessageMediaDocument):
                mime = getattr(msg.media.document, "mime_type", "")
                if mime.startswith("video"):
                    item["media_type"] = "video"
                    path = await client.download_media(msg.media, str(media_folder / f"{msg.id}.mp4"))
                    item["media_path"] = str(path) if path else None

        await on_message(item)

    print(f"[PARSER] Real-time listening: {channels}")
    await client.run_until_disconnected()
