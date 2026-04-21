"""
Парсинг ТГ — генератор каруселей

Флоу:
  1. Telethon (userbot) читает чужой SOURCE_CHANNELS
  2. Новый пост → бот шлёт тему в личку с кнопкой «Создать карусель»
  3. Ты одобряешь
  4. Gemini 2.5 Flash планирует слайды → Gemini Image Gen рисует картинки
  5. Pillow накладывает текст → бот постит карусель в твой канал

.env:
  TELEGRAM_BOT_TOKEN        — токен бота (должен быть админом в твоём канале)
  TELEGRAM_CHANNEL_CHAT_ID  — ID твоего канала куда публиковать
  NOTIFY_CHAT_ID            — твой личный chat_id для кнопок одобрения
  TG_API_ID / TG_API_HASH   — с my.telegram.org (для Telethon)
  SESSION_FILE              — путь к .session файлу
  SOURCE_CHANNELS           — @channel1,@channel2  (откуда парсим)
  GEMINI_API_KEY
  SLIDE_COUNT=5
  MIN_TEXT_LEN=80           — игнорировать посты короче N символов
  MODE=polling              — polling | webhook
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
from starlette.responses import JSONResponse
from starlette.templating import Jinja2Templates

from tools.telegram import (
    send_message_with_buttons,
    edit_message_text,
    answer_callback_query,
    send_photo_album,
    notify_admin,
    get_updates,
    delete_webhook,
    load_offset,
    save_offset,
)
from tools.gemini_carousel import create_carousel
from tools.parser import start_listening, is_authorized, SOURCE_CHANNELS

CHANNEL_CHAT_ID = os.getenv("TELEGRAM_CHANNEL_CHAT_ID", "")
NOTIFY_CHAT_ID  = os.getenv("NOTIFY_CHAT_ID", "")
SLIDE_COUNT     = int(os.getenv("SLIDE_COUNT", "5"))
MIN_TEXT_LEN    = int(os.getenv("MIN_TEXT_LEN", "80"))
WEBHOOK_URL     = os.getenv("WEBHOOK_URL", "").rstrip("/")

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# key → {topic, source, channel_id}
_pending: dict[str, dict] = {}
_pending_lock = asyncio.Lock()


# ─── Step 1: Telethon got a new post ─────────────────────────────────────────

async def on_parsed_post(text: str, source: str, msg_id: int) -> None:
    """Called by Telethon when a new post appears in a source channel."""
    if len(text) < MIN_TEXT_LEN:
        return

    approve_key = f"approve_{source}_{msg_id}"
    preview = text[:300] + ("…" if len(text) > 300 else "")

    msg = (
        f"📡 <b>Новый пост из {source}</b>\n\n"
        f"{preview}\n\n"
        f"Создать карусель из <b>{SLIDE_COUNT} слайдов</b>?"
    )
    buttons = [[
        {"text": "✅ Создать карусель", "callback_data": approve_key},
        {"text": "❌ Пропустить",        "callback_data": f"reject_{source}_{msg_id}"},
    ]]

    result = await send_message_with_buttons(NOTIFY_CHAT_ID, msg, buttons)
    notify_msg_id = result.get("result", {}).get("message_id", 0)

    async with _pending_lock:
        _pending[approve_key] = {
            "topic": text,
            "source": source,
            "channel_id": CHANNEL_CHAT_ID,
            "notify_msg_id": notify_msg_id,
        }

    print(f"[MAIN] Пост из {source} отправлен на одобрение ({len(text)} символов)")


# ─── Step 2: Admin pressed a button ──────────────────────────────────────────

async def handle_callback_query(callback: dict) -> None:
    cb_id   = callback.get("id", "")
    data    = callback.get("data", "")
    chat_id = str(callback.get("message", {}).get("chat", {}).get("id", ""))
    msg_id  = callback.get("message", {}).get("message_id", 0)

    if data.startswith("reject_"):
        await answer_callback_query(cb_id, "Пропущено")
        await edit_message_text(chat_id, msg_id, "⏭ Пост пропущен")
        key = data.replace("reject_", "approve_", 1)
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
    source     = entry.get("source", "")
    channel_id = entry.get("channel_id", CHANNEL_CHAT_ID)

    await answer_callback_query(cb_id, "Генерирую…")
    await edit_message_text(chat_id, msg_id,
        f"⏳ <b>Генерирую карусель…</b>\n\nИсточник: {source}")

    try:
        images, slides = await create_carousel(topic, count=SLIDE_COUNT, channel=source)

        first_title = slides[0].get("title", "") if slides else ""
        first_body  = slides[0].get("body", "") if slides else ""
        caption = f"<b>{first_title}</b>\n{first_body}" if first_title else topic[:200]

        await send_photo_album(channel_id, images, caption=caption)

        await edit_message_text(chat_id, msg_id,
            f"✅ <b>Карусель опубликована</b> ({len(images)} слайдов)\n\n"
            f"Источник: {source}")
        print(f"[MAIN] Карусель опубликована: {len(images)} слайдов из {source}")

    except Exception as e:
        import traceback
        traceback.print_exc()
        err = str(e)[:300]
        await edit_message_text(chat_id, msg_id, f"❌ <b>Ошибка генерации</b>\n\n{err}")
        await notify_admin(f"❌ Ошибка генерации карусели:\n{err}")


# ─── Bot update dispatcher ────────────────────────────────────────────────────

async def dispatch(update: dict) -> None:
    if "callback_query" in update:
        asyncio.create_task(handle_callback_query(update["callback_query"]))


# ─── Bot polling loop ─────────────────────────────────────────────────────────

async def run_bot_polling() -> None:
    await delete_webhook()
    print("[BOT] Polling запущен")
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
            print(f"[BOT ERROR] {e}")
            traceback.print_exc()
            await asyncio.sleep(3)


# ─── Webhook mode ─────────────────────────────────────────────────────────────

async def webhook_handler(request: Request) -> JSONResponse:
    update = await request.json()
    await dispatch(update)
    return JSONResponse({"ok": True})


async def _register_webhook() -> None:
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
    print(f"[WEBHOOK] {'Зарегистрирован: ' + target if res.get('ok') else 'Ошибка: ' + str(res)}")


# ─── Web UI ───────────────────────────────────────────────────────────────────

async def homepage(request: Request):
    return templates.TemplateResponse(request, "index.html", {
        "channel": CHANNEL_CHAT_ID,
        "slide_count": SLIDE_COUNT,
        "source_channels": SOURCE_CHANNELS,
    })


async def api_status(request: Request) -> JSONResponse:
    authorized = await is_authorized()
    return JSONResponse({
        "gemini_key":     bool(os.getenv("GEMINI_API_KEY")),
        "bot_token":      bool(os.getenv("TELEGRAM_BOT_TOKEN")),
        "tg_auth":        authorized,
        "source_channels": SOURCE_CHANNELS,
        "channel":        CHANNEL_CHAT_ID,
        "notify_chat":    NOTIFY_CHAT_ID,
        "slide_count":    SLIDE_COUNT,
        "pending":        len(_pending),
    })


# Auth endpoints (первый раз нужно залогиниться в Telethon)
async def auth_send_code(request: Request) -> JSONResponse:
    from tools.parser import send_code
    body = await request.json()
    phone = body.get("phone", "").strip()
    if not phone:
        return JSONResponse({"status": "error", "reason": "phone required"}, status_code=400)
    try:
        phone_code_hash = await send_code(phone)
        return JSONResponse({"status": "ok", "phone_code_hash": phone_code_hash})
    except Exception as e:
        return JSONResponse({"status": "error", "reason": str(e)}, status_code=500)


async def auth_verify(request: Request) -> JSONResponse:
    from tools.parser import sign_in
    body = await request.json()
    result = await sign_in(
        body.get("phone", ""),
        body.get("code", ""),
        body.get("phone_code_hash", ""),
    )
    return JSONResponse(result)


@asynccontextmanager
async def lifespan(app):
    if WEBHOOK_URL:
        await _register_webhook()
    yield


app = Starlette(
    routes=[
        Route("/",               endpoint=homepage,       methods=["GET"]),
        Route("/webhook",        endpoint=webhook_handler, methods=["POST"]),
        Route("/api/status",     endpoint=api_status,     methods=["GET"]),
        Route("/auth/send-code", endpoint=auth_send_code, methods=["POST"]),
        Route("/auth/verify",    endpoint=auth_verify,    methods=["POST"]),
    ],
    lifespan=lifespan,
)


# ─── Entry point ──────────────────────────────────────────────────────────────

async def run_all() -> None:
    """Run Telethon parser + Bot polling concurrently."""
    await asyncio.gather(
        start_listening(on_parsed_post),
        run_bot_polling(),
    )


if __name__ == "__main__":
    mode = os.getenv("MODE", "polling")
    if mode == "polling":
        asyncio.run(run_all())
    else:
        import uvicorn
        uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")
