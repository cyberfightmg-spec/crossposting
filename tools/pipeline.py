"""
Пайплайн: Telethon → OpenAI → Pillow → instagrapi

Для каждого нового поста в канале:
  1. Получаем текст + скачиваем фото через Telethon
  2. OpenAI делит пост на слайды [{title, body}, ...]
  3. Pillow рендерит каждый слайд как PNG 1080x1080
  4. instagrapi заливает album_upload() → карусель в Instagram
"""

import asyncio
import os
import tempfile
from pathlib import Path

from telethon import TelegramClient, events
from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument

from tools.ai_adapter import split_into_slides
from tools.card_renderer import render_cards
from tools.instagram import get_ig_client  # async → returns instagrapi Client

API_ID = int(os.getenv("TG_API_ID", "0"))
API_HASH = os.getenv("TG_API_HASH", "")
SESSION_FILE = os.getenv("SESSION_FILE", "/root/tg_parser.session")
CHANNELS = [c.strip() for c in os.getenv("PARSE_CHANNELS", "").split(",") if c.strip()]
MIN_TEXT_LEN = int(os.getenv("MIN_TEXT_LEN", "100"))
MAX_SLIDES = int(os.getenv("MAX_SLIDES", "7"))
TMP_DIR = Path(tempfile.gettempdir()) / "tg_cards"
TMP_DIR.mkdir(exist_ok=True)


async def _post_carousel(slides: list[dict], channel: str) -> dict:
    """Render slides and upload to Instagram as album."""
    card_bytes_list = render_cards(slides, channel=channel)

    paths: list[Path] = []
    for i, data in enumerate(card_bytes_list):
        p = TMP_DIR / f"card_{i:02d}.png"
        p.write_bytes(data)
        paths.append(p)

    try:
        cl = await get_ig_client()
        loop = asyncio.get_event_loop()
        caption = slides[0].get("title", "") if slides else ""
        media = await loop.run_in_executor(
            None, lambda: cl.album_upload([str(p) for p in paths], caption=caption)
        )
        return {"status": "ok", "media_id": str(media.pk)}
    except Exception as e:
        return {"status": "error", "reason": str(e)}
    finally:
        for p in paths:
            p.unlink(missing_ok=True)


async def _handle_message(event, client: TelegramClient) -> None:
    msg = event.message
    text: str = msg.text or msg.message or ""

    # Skip short posts (service messages, stickers, etc.)
    if len(text) < MIN_TEXT_LEN:
        return

    try:
        chat = await event.get_chat()
        channel = f"@{getattr(chat, 'username', str(chat.id))}"
    except Exception:
        channel = ""

    print(f"[PIPELINE] New post from {channel}: {len(text)} chars")

    slides = await split_into_slides(text, max_slides=MAX_SLIDES)
    print(f"[PIPELINE] Split into {len(slides)} slides")

    result = await _post_carousel(slides, channel=channel)
    status = result.get("status")
    if status == "ok":
        print(f"[PIPELINE] ✅ Posted carousel, media_id={result.get('media_id')}")
    else:
        print(f"[PIPELINE] ❌ Instagram error: {result.get('reason')}")


async def run_parser(channels: list[str] | None = None) -> None:
    """Connect Telethon and start listening for new messages."""
    targets = channels or CHANNELS
    if not targets:
        raise ValueError("No channels configured. Set PARSE_CHANNELS in .env")

    client = TelegramClient(SESSION_FILE, API_ID, API_HASH)

    @client.on(events.NewMessage(chats=targets))
    async def handler(event):
        try:
            await _handle_message(event, client)
        except Exception as e:
            import traceback
            print(f"[PIPELINE ERROR] {e}")
            traceback.print_exc()

    await client.start()
    print(f"[PARSER] Listening to: {targets}")
    await client.run_until_disconnected()


async def parse_history(channel: str, limit: int = 20) -> list[dict]:
    """Parse historical posts and return a list of pipeline results."""
    client = TelegramClient(SESSION_FILE, API_ID, API_HASH)
    await client.connect()

    results = []
    async for msg in client.iter_messages(channel, limit=limit):
        text = msg.text or msg.message or ""
        if len(text) < MIN_TEXT_LEN:
            continue

        slides = await split_into_slides(text, max_slides=MAX_SLIDES)
        result = await _post_carousel(slides, channel=channel)
        results.append({
            "msg_id": msg.id,
            "slides": len(slides),
            **result,
        })

    await client.disconnect()
    return results
