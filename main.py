"""
Парсинг ТГ — генератор каруселей

Флоу:
  1. Пользователь кидает тему в Telegram-канал
  2. Бот пересылает в чат к админу с кнопкой «Создать карусель»
  3. Админ одобряет
  4. Gemini 2.5 Flash планирует слайды → Gemini генерирует картинки
  5. Pillow накладывает текст
  6. Бот постит готовую карусель в канал

Переменные в .env:
  TELEGRAM_BOT_TOKEN        — токен бота
  TELEGRAM_CHANNEL_CHAT_ID  — ID канала (бот должен быть админом)
  NOTIFY_CHAT_ID            — куда слать запросы одобрения (личный чат)
  GEMINI_API_KEY
  WEBHOOK_URL               — если webhook-режим (https://yourdomain/webhook)
  MODE                      — polling (default) | webhook
  SLIDE_COUNT               — количество слайдов (default: 5)
"""

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from starlette.applications import Starlette
from starlette.routing import Route
from starlette.requests import Request
from starlette.responses import JSONResponse, HTMLResponse
from starlette.templating import Jinja2Templates

from tools.telegram import (
    send_message,
    send_message_with_buttons,
    edit_message_text,
    answer_callback_query,
    send_photo_album,
    notify_admin,
    get_updates,
    delete_webhook,
    load_offset,
    save_offset,
    BASE_URL,
)
from tools.gemini_carousel import create_carousel

CHANNEL_CHAT_ID = os.getenv("TELEGRAM_CHANNEL_CHAT_ID", "")
NOTIFY_CHAT_ID  = os.getenv("NOTIFY_CHAT_ID", "")
SLIDE_COUNT     = int(os.getenv("SLIDE_COUNT", "5"))
WEBHOOK_URL     = os.getenv("WEBHOOK_URL", "").rstrip("/")

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Pending approvals: approve_key → {topic, channel_id, notify_msg_id}
_pending: dict[str, dict] = {}
_pending_lock = asyncio.Lock()


# ─── Core logic ───────────────────────────────────────────────────────────────

async def handle_channel_post(post: dict) -> None:
    """New text post in channel → send approval request to admin."""
    text = (post.get("text") or post.get("caption") or "").strip()
    if not text:
        return

    chat_id  = str(post.get("chat", {}).get("id", CHANNEL_CHAT_ID))
    msg_id   = post.get("message_id", 0)
    approve_key = f"approve_{msg_id}"

    preview = text[:200] + ("…" if len(text) > 200 else "")
    msg = (
        f"📌 <b>Новая тема для карусели</b>\n\n"
        f"{preview}\n\n"
        f"Создать карусель из <b>{SLIDE_COUNT} слайдов</b>?"
    )
    buttons = [[
        {"text": "✅ Создать карусель", "callback_data": approve_key},
        {"text": "❌ Отклонить",        "callback_data": f"reject_{msg_id}"},
    ]]

    result = await send_message_with_buttons(NOTIFY_CHAT_ID, msg, buttons)
    notify_msg_id = result.get("result", {}).get("message_id", 0)

    async with _pending_lock:
        _pending[approve_key] = {
            "topic": text,
            "channel_id": chat_id,
            "notify_msg_id": notify_msg_id,
        }

    print(f"[MAIN] Тема отправлена на одобрение: {text[:60]}")


async def handle_callback_query(callback: dict) -> None:
    """Admin pressed a button → generate carousel or reject."""
    cb_id   = callback.get("id", "")
    data    = callback.get("data", "")
    chat_id = str(callback.get("message", {}).get("chat", {}).get("id", ""))
    msg_id  = callback.get("message", {}).get("message_id", 0)

    if data.startswith("reject_"):
        await answer_callback_query(cb_id, "Отклонено")
        await edit_message_text(chat_id, msg_id, "❌ Тема отклонена")
        key = data.replace("reject_", "approve_")
        async with _pending_lock:
            _pending.pop(key, None)
        return

    if not data.startswith("approve_"):
        return

    async with _pending_lock:
        entry = _pending.pop(data, None)

    if not entry:
        await answer_callback_query(cb_id, "Уже обработано")
        return

    topic      = entry["topic"]
    channel_id = entry["channel_id"]

    await answer_callback_query(cb_id, "Генерирую…")
    await edit_message_text(chat_id, msg_id,
        f"⏳ <b>Генерирую карусель…</b>\n\n{topic[:200]}")

    try:
        channel_username = ""
        # Try to get channel username from topic context (optional decoration)
        images, slides = await create_carousel(topic, count=SLIDE_COUNT, channel=channel_username)

        first_title   = slides[0].get("title", "") if slides else ""
        first_body    = slides[0].get("body", "") if slides else ""
        caption = f"<b>{first_title}</b>\n{first_body}" if first_title else topic[:200]

        await send_photo_album(channel_id, images, caption=caption)

        await edit_message_text(chat_id, msg_id,
            f"✅ <b>Карусель опубликована</b> ({len(images)} слайдов)\n\n{topic[:120]}")
        print(f"[MAIN] Карусель опубликована: {len(images)} слайдов")

    except Exception as e:
        import traceback
        traceback.print_exc()
        err = str(e)[:200]
        await edit_message_text(chat_id, msg_id,
            f"❌ <b>Ошибка генерации</b>\n\n{err}")
        await notify_admin(f"❌ Ошибка генерации карусели:\n{err}")


async def dispatch(update: dict) -> None:
    """Route incoming Telegram update."""
    if "channel_post" in update:
        post = update["channel_post"]
        # Filter to our channel if configured
        if CHANNEL_CHAT_ID:
            if str(post.get("chat", {}).get("id", "")) != CHANNEL_CHAT_ID:
                return
        asyncio.create_task(handle_channel_post(post))

    elif "callback_query" in update:
        asyncio.create_task(handle_callback_query(update["callback_query"]))


# ─── Webhook mode ─────────────────────────────────────────────────────────────

async def webhook_handler(request: Request) -> JSONResponse:
    update = await request.json()
    await dispatch(update)
    return JSONResponse({"ok": True})


async def _register_webhook():
    import httpx as _httpx
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not WEBHOOK_URL or not bot_token:
        return
    target = f"{WEBHOOK_URL}/webhook"
    async with _httpx.AsyncClient() as client:
        r = await client.post(
            f"https://api.telegram.org/bot{bot_token}/setWebhook",
            json={"url": target, "drop_pending_updates": False},
            timeout=10,
        )
        res = r.json()
    if res.get("ok"):
        print(f"[WEBHOOK] Зарегистрирован: {target}")
    else:
        print(f"[WEBHOOK] Ошибка: {res}")


# ─── Web app ──────────────────────────────────────────────────────────────────

async def homepage(request: Request):
    return templates.TemplateResponse(request, "index.html", {
        "channel": CHANNEL_CHAT_ID,
        "slide_count": SLIDE_COUNT,
        "webhook_url": WEBHOOK_URL,
    })


async def api_status(request: Request) -> JSONResponse:
    return JSONResponse({
        "gemini_key": bool(os.getenv("GEMINI_API_KEY")),
        "bot_token": bool(os.getenv("TELEGRAM_BOT_TOKEN")),
        "channel": CHANNEL_CHAT_ID,
        "notify_chat": NOTIFY_CHAT_ID,
        "slide_count": SLIDE_COUNT,
        "pending": len(_pending),
    })


@asynccontextmanager
async def lifespan(app):
    if WEBHOOK_URL:
        await _register_webhook()
    yield


app = Starlette(
    routes=[
        Route("/", endpoint=homepage, methods=["GET"]),
        Route("/webhook", endpoint=webhook_handler, methods=["POST"]),
        Route("/api/status", endpoint=api_status, methods=["GET"]),
    ],
    lifespan=lifespan,
)


# ─── Polling mode ─────────────────────────────────────────────────────────────

async def run_polling():
    await delete_webhook()
    print("[POLLING] Запущен, жду обновлений…")
    offset = load_offset()
    while True:
        try:
            result = await get_updates(offset=offset, timeout=30)
            if result.get("ok"):
                for update in result.get("result", []):
                    offset = update["update_id"] + 1
                    save_offset(offset)
                    await dispatch(update)
        except Exception as e:
            import traceback
            print(f"[POLLING ERROR] {e}")
            traceback.print_exc()
            await asyncio.sleep(3)


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mode = os.getenv("MODE", "polling")
    if mode == "polling":
        asyncio.run(run_polling())
    else:
        import uvicorn
        uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")
