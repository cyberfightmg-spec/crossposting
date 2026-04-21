"""
Парсинг ТГ — Telegram → Instagram карусель

Пайплайн:
  Telethon слушает чужой канал
  → OpenAI делит текст на слайды
  → Pillow рендерит PNG-карточки 1080x1080
  → instagrapi заливает album_upload() → карусель в Instagram

Запуск:
  MODE=listen  python main.py   # real-time (по умолчанию)
  MODE=history python main.py   # парсинг истории
  MODE=web     python main.py   # веб-интерфейс
"""

import os
import sys
import asyncio
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from starlette.applications import Starlette
from starlette.routing import Route, Mount
from starlette.requests import Request
from starlette.responses import JSONResponse, HTMLResponse
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

from tools.parser import send_code, sign_in, is_authorized, parse_channel
from tools.pipeline import run_parser, parse_history

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

CHANNELS = [c.strip() for c in os.getenv("PARSE_CHANNELS", "").split(",") if c.strip()]


# ─── Web routes ───────────────────────────────────────────────────────────────

async def homepage(request: Request) -> HTMLResponse:
    authorized = await is_authorized()
    return templates.TemplateResponse(request, "parser.html", {
        "authorized": authorized,
        "channels": CHANNELS,
    })


async def auth_send_code(request: Request) -> JSONResponse:
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
    body = await request.json()
    phone = body.get("phone", "").strip()
    code = body.get("code", "").strip()
    phone_code_hash = body.get("phone_code_hash", "").strip()
    result = await sign_in(phone, code, phone_code_hash)
    return JSONResponse(result)


async def api_parse_history(request: Request) -> JSONResponse:
    channel = request.query_params.get("channel", "").strip()
    limit = int(request.query_params.get("limit", "10"))
    if not channel:
        return JSONResponse({"status": "error", "reason": "channel required"}, status_code=400)
    try:
        results = await parse_history(channel, limit=limit)
        return JSONResponse({"status": "ok", "results": results})
    except Exception as e:
        return JSONResponse({"status": "error", "reason": str(e)}, status_code=500)


async def api_status(request: Request) -> JSONResponse:
    authorized = await is_authorized()
    return JSONResponse({
        "authorized": authorized,
        "channels": CHANNELS,
        "api_id_set": bool(os.getenv("TG_API_ID")),
        "ig_set": bool(os.getenv("INSTAGRAM_USERNAME")),
        "openai_set": bool(os.getenv("OPENAI_API_KEY")),
    })


# ─── App ──────────────────────────────────────────────────────────────────────

MEDIA_DIR = Path("/tmp/tg_cards")
MEDIA_DIR.mkdir(exist_ok=True)

app = Starlette(
    routes=[
        Route("/", endpoint=homepage, methods=["GET"]),
        Route("/auth/send-code", endpoint=auth_send_code, methods=["POST"]),
        Route("/auth/verify", endpoint=auth_verify, methods=["POST"]),
        Route("/api/parse", endpoint=api_parse_history, methods=["GET"]),
        Route("/api/status", endpoint=api_status, methods=["GET"]),
    ],
)


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mode = os.getenv("MODE", "listen")

    if mode == "listen":
        print("[MAIN] Режим: real-time парсинг каналов")
        asyncio.run(run_parser())

    elif mode == "history":
        channel = os.getenv("PARSE_CHANNELS", "").split(",")[0].strip()
        limit = int(os.getenv("HISTORY_LIMIT", "20"))
        print(f"[MAIN] Режим: история — {channel}, лимит {limit}")
        results = asyncio.run(parse_history(channel, limit))
        for r in results:
            print(r)

    elif mode == "web":
        import uvicorn
        print("[MAIN] Режим: веб-интерфейс на :8080")
        uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")

    else:
        print(f"Неизвестный MODE={mode}. Используй: listen | history | web")
        sys.exit(1)
