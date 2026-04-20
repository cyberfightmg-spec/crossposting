import os
import json
import asyncio
import base64
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

import httpx
from fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.routing import Mount, Route
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, HTMLResponse
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates
from tools.router import detect_type
from tools.telegram import send_message, notify_admin, BASE_URL
from tools.vk import post_text_vk, post_photo_vk, post_video_vk
from tools.dzen import post_dzen
from tools.pinterest import post_to_pinterest, _refresh_access_token
from tools.wordstat import get_keywords
from tools.ai_adapter import adapt_vk, adapt_dzen, adapt_youtube
from tools.carousel import process_carousel, cleanup_carousel
from tools.instagram import post_to_instagram, post_reel_instagram
from tools.instagram_graph import post_photo as ig_post_photo
from tools.instagram_graph import post_carousel as ig_post_carousel
from tools.instagram_graph import post_reel as ig_post_reel
from tools.instagram_graph import is_configured as ig_graph_configured
from tools.media_host import copy_to_media, save_media, delete_media, MEDIA_DIR
from tools.instagram_media import (
    create_dated_folder,
    save_photos_batch,
    save_video_with_cover,
    cleanup_dated_folder,
)

MEDIA_DIR.mkdir(parents=True, exist_ok=True)

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

mcp = FastMCP("crosspost-server")

# Enable/disable platforms based on .env flags
ENABLED_PLATFORMS = {
    "vk": os.getenv("VK_ENABLED", "true").lower() == "true",
    "dzen": os.getenv("DZEN_ENABLED", "true").lower() == "true",
    "instagram": os.getenv("INSTAGRAM_ENABLED", "false").lower() == "true",
    "pinterest": os.getenv("PINTEREST_ENABLED", "false").lower() == "true",
    "linkedin": os.getenv("LINKEDIN_ENABLED", "false").lower() == "true",
}


def detect_content_type(post: dict) -> str:
    if post.get("_merged"):
        photos = post.get("photo", [])
        if len(photos) > 1:
            return "SLIDES"
        elif len(photos) == 1:
            return "PHOTO"
    if post.get("video") or post.get("animation"):
        return "VIDEO"
    if post.get("text") and not post.get("photo"):
        return "TEXT"
    if post.get("media_group_id"):
        return "SLIDES"
    if post.get("photo"):
        return "PHOTO"
    if post.get("text"):
        return "TEXT"
    return "UNKNOWN"


async def send_crosspost_notification(channel_post: dict, result: dict) -> None:
    content_type = detect_content_type(channel_post)
    preview = ""
    if content_type == "TEXT":
        text = channel_post.get("text", "")[:100]
        preview = f"Текст: {text}..."
    elif content_type == "SLIDES":
        photos = channel_post.get("photo", [])
        count = channel_post.get("_parts_count", len(photos)) if channel_post.get("_merged") else len(photos)
        preview = f"Слайды: {count} фото"
    elif content_type == "PHOTO":
        preview = "Фото"
    elif content_type == "VIDEO":
        preview = "Видео (Reels)"

    chat = channel_post.get("chat", {})
    channel_title = chat.get("title", "Неизвестный канал")
    channel_username = chat.get("username", "")
    
    if channel_username:
        channel_name = f"@{channel_username}"
    else:
        channel_name = channel_title

    from datetime import datetime
    
    publish_time = datetime.now().strftime("%d.%m.%Y %H:%M")
    
    msg = f"📤 Кросспостинг\n\nКанал: {channel_name}\n{preview}\n\n"
    
    platforms = result.get("platforms", {})
    platform_names = {
        "vk": "VK",
        "instagram": "Instagram", 
        "pinterest": "Pinterest",
        "dzen": "Дзен",
        "youtube": "YouTube",
    }
    
    for platform, status in platforms.items():
        name = platform_names.get(platform, platform.capitalize())
        if status == "ok":
            msg += f"✅ {name:<12} ({publish_time})\n"
        elif status == "disabled":
            msg += f"⏸ {name:<12} (отключено)\n"
        elif status == "error":
            msg += f"❌ {name:<12} (ошибка)\n"
        elif status == "logged":
            msg += f"📝 {name:<12} (залогировано)\n"
    
    if result.get("errors"):
        msg += f"\nОшибки: {result['errors']}"
    
    await notify_admin(msg)


CHANNEL_CHAT_ID = os.getenv("TELEGRAM_CHANNEL_CHAT_ID", "")


async def webhook_handler(request: Request) -> JSONResponse:
    """Принимает update от Telegram, сразу возвращает 200, обработку запускает фоном."""
    update = await request.json()

    if "channel_post" in update:
        chat_id = str(update["channel_post"].get("chat", {}).get("id", ""))
        if CHANNEL_CHAT_ID and chat_id != CHANNEL_CHAT_ID:
            return JSONResponse({"ok": True})
        asyncio.create_task(crosspost(update))

    return JSONResponse({"ok": True})


carousel_cache = {}
carousel_lock = asyncio.Lock()
carousel_tasks = {}


async def _fire_carousel(media_group_id: str):
    """Фоновая задача: ждёт 5 секунд после первого фото, затем мёрджит и постит карусель"""
    await asyncio.sleep(5.0)

    async with carousel_lock:
        if media_group_id not in carousel_cache:
            return
        entry = carousel_cache.pop(media_group_id)
        carousel_tasks.pop(media_group_id, None)

    parts = entry["parts"]
    print(f"[CAROUSEL] Firing {media_group_id}: {len(parts)} parts collected")

    try:
        merged = merge_parts(parts)
        await _do_crosspost(merged)
    except Exception as e:
        import traceback
        print(f"[CAROUSEL ERROR] {media_group_id}: {e}")
        traceback.print_exc()


def merge_parts(parts: list) -> dict:
    """Объединяет части карусели в один пост - только оригиналы (макс. размер)"""
    all_photos = []
    caption = ""
    
    print(f"[MERGE] Received {len(parts)} parts")
    for i, part in enumerate(parts):
        photos = part.get("photo", [])
        print(f"[MERGE] Part {i}: {len(photos)} photos")
        
        # Debug: print all file_ids to understand structure
        seen_file_ids = set()
        for j, p in enumerate(photos):
            file_id = p.get("file_id", "n/a")
            file_size = p.get("file_size", 0)
            width = p.get("width", 0)
            is_new = file_id not in seen_file_ids
            if is_new:
                seen_file_ids.add(file_id)
            print(f"[MERGE]   Photo {j}: id={file_id[:30]}... w={width} size={file_size} is_new={is_new}")
        
        # Take only the last photo (max resolution)
        if photos:
            original = photos[-1]
            file_id = original.get("file_id", "no_id")
            file_size = original.get("file_size", 0)
            print(f"[MERGE] Taking original: id={file_id[:20]}... size={file_size}")
            all_photos.append(original)
        
        if not caption:
            caption = part.get("caption") or part.get("text", "")
    
    merged = parts[0].copy()
    merged["photo"] = all_photos
    merged["caption"] = caption
    merged["_merged"] = True
    merged["_parts_count"] = len(parts)
    print(f"[MERGE] Total photos: {len(all_photos)}")
    return merged


async def crosspost(update: dict) -> dict:
    """Router: буферизует карусели, остальной контент публикует сразу"""
    channel_post = update.get("channel_post", {})
    media_group_id = channel_post.get("media_group_id")

    if media_group_id:
        async with carousel_lock:
            if media_group_id not in carousel_cache:
                carousel_cache[media_group_id] = {"parts": []}
                task = asyncio.create_task(_fire_carousel(media_group_id))
                carousel_tasks[media_group_id] = task
                print(f"[CAROUSEL] Started buffering {media_group_id}")
            carousel_cache[media_group_id]["parts"].append(channel_post)
            count = len(carousel_cache[media_group_id]["parts"])
            print(f"[CAROUSEL] Buffered part {count} for {media_group_id}")
        return {"status": "buffering"}

    return await _do_crosspost(channel_post)


async def _do_crosspost(channel_post: dict) -> dict:
    """Определяет тип контента и публикует на всех платформах"""
    result = {"status": "ok", "platforms": {}, "errors": []}

    content_type = detect_content_type(channel_post)
    photos = channel_post.get("photo", [])
    print(f"[DEBUG] content_type={content_type}, photos={len(photos)}, merged={channel_post.get('_merged', False)}")

    if content_type == "TEXT":
        text = channel_post.get("text", "")

        async def run_vk():
            if not ENABLED_PLATFORMS["vk"]:
                result["platforms"]["vk"] = "disabled"
                return
            try:
                adapted = await adapt_vk(text)
                vk_result = await post_text_vk(adapted)
                result["platforms"]["vk"] = "ok" if vk_result.get("response") else "error"
            except Exception as e:
                result["platforms"]["vk"] = "error"
                result["errors"].append(f"vk: {str(e)}")

        async def run_dzen():
            if not ENABLED_PLATFORMS["dzen"]:
                result["platforms"]["dzen"] = "disabled"
                return
            try:
                keywords = await get_keywords(text)
                adapted = await adapt_dzen(text, keywords)
                dzen_result = await post_dzen(adapted)
                result["platforms"]["dzen"] = "ok" if dzen_result.get("status") == "ok" else "error"
            except Exception as e:
                result["platforms"]["dzen"] = "error"
                result["errors"].append(f"dzen: {str(e)}")

        async def run_youtube():
            try:
                await adapt_youtube(text)
                result["platforms"]["youtube"] = "logged"
            except Exception as e:
                result["errors"].append(f"youtube: {str(e)}")

        await asyncio.gather(run_vk(), run_dzen(), run_youtube())

    elif content_type == "SLIDES":
        file_ids = [p["file_id"] for p in photos]
        caption = channel_post.get("caption", "")
        print(f"[DEBUG] SLIDES: {len(file_ids)} photos, {len(set(file_ids))} unique file_ids")

        carousel = await process_carousel(file_ids)

        async def run_vk():
            if not ENABLED_PLATFORMS["vk"]:
                result["platforms"]["vk"] = "disabled"
                return
            try:
                vk_result = await post_photo_vk(carousel["local_paths"], caption, carousel=True)
                if vk_result.get("response"):
                    result["platforms"]["vk"] = "ok"
                else:
                    result["platforms"]["vk"] = "error"
                    result["errors"].append(f"vk: {vk_result.get('error', 'unknown')}")
            except Exception as e:
                result["platforms"]["vk"] = "error"
                result["errors"].append(f"vk: {str(e)}")

        async def run_pinterest():
            if not ENABLED_PLATFORMS["pinterest"]:
                result["platforms"]["pinterest"] = "disabled"
                return
            try:
                await post_to_pinterest(carousel["local_paths"], caption)
                result["platforms"]["pinterest"] = "ok"
            except Exception as e:
                result["platforms"]["pinterest"] = "error"
                result["errors"].append(f"pinterest: {str(e)}")

        async def run_dzen():
            if not ENABLED_PLATFORMS["dzen"]:
                result["platforms"]["dzen"] = "disabled"
                return
            try:
                dzen_result = await post_dzen({"urls": carousel["dzen"], "caption": caption})
                result["platforms"]["dzen"] = "ok" if dzen_result.get("status") == "ok" else "error"
            except Exception as e:
                result["platforms"]["dzen"] = "error"
                result["errors"].append(f"dzen: {str(e)}")

        async def run_instagram():
            if not ENABLED_PLATFORMS["instagram"]:
                result["platforms"]["instagram"] = "disabled"
                return
            folder_name = None
            try:
                if ig_graph_configured():
                    # Graph API: сохраняем фото в датированную папку и получаем публичные URL
                    folder_name = create_dated_folder()
                    # Читаем байты из локальных файлов карусели
                    photo_bytes_list = [open(p, "rb").read() for p in carousel["local_paths"]]
                    _, public_urls = save_photos_batch(photo_bytes_list, folder_name)
                    ig_result = await ig_post_carousel(public_urls, caption)
                else:
                    ig_result = await post_to_instagram(carousel["local_paths"], caption)
                result["platforms"]["instagram"] = "ok" if ig_result.get("status") == "ok" else "error"
                if ig_result.get("status") != "ok":
                    result["errors"].append(f"instagram: {ig_result.get('reason', 'unknown')}")
            except Exception as e:
                result["platforms"]["instagram"] = "error"
                result["errors"].append(f"instagram: {str(e)}")
            finally:
                if folder_name:
                    # Удаляем папку через 60 сек, чтобы Instagram успел скачать файлы
                    asyncio.create_task(cleanup_dated_folder(folder_name, delay_seconds=60))

        await asyncio.gather(run_vk(), run_pinterest(), run_dzen(), run_instagram())
        await cleanup_carousel(carousel["carousel_id"])

    elif content_type == "PHOTO":
        file_id = channel_post["photo"][-1]["file_id"]
        caption = channel_post.get("caption", "")

        carousel = await process_carousel([file_id])

        async def run_vk():
            if not ENABLED_PLATFORMS["vk"]:
                result["platforms"]["vk"] = "disabled"
                return
            try:
                vk_result = await post_photo_vk(carousel["local_paths"], caption)
                result["platforms"]["vk"] = "ok" if vk_result.get("response") else "error"
            except Exception as e:
                result["platforms"]["vk"] = "error"
                result["errors"].append(f"vk: {str(e)}")

        async def run_pinterest():
            if not ENABLED_PLATFORMS["pinterest"]:
                result["platforms"]["pinterest"] = "disabled"
                return
            try:
                await post_to_pinterest(carousel["local_paths"], caption)
                result["platforms"]["pinterest"] = "ok"
            except Exception as e:
                result["platforms"]["pinterest"] = "error"
                result["errors"].append(f"pinterest: {str(e)}")

        async def run_instagram():
            if not ENABLED_PLATFORMS["instagram"]:
                result["platforms"]["instagram"] = "disabled"
                return
            folder_name = None
            try:
                if ig_graph_configured():
                    # Graph API: сохраняем фото в датированную папку
                    folder_name = create_dated_folder()
                    photo_bytes = open(carousel["local_paths"][0], "rb").read()
                    _, public_url = save_photos_batch([photo_bytes], folder_name)
                    ig_result = await ig_post_photo(public_url[0], caption)
                else:
                    ig_result = await post_to_instagram(carousel["local_paths"], caption)
                result["platforms"]["instagram"] = "ok" if ig_result.get("status") == "ok" else "error"
                if ig_result.get("status") != "ok":
                    result["errors"].append(f"instagram: {ig_result.get('reason', 'unknown')}")
            except Exception as e:
                result["platforms"]["instagram"] = "error"
                result["errors"].append(f"instagram: {str(e)}")
            finally:
                if folder_name:
                    # Удаляем папку через 60 сек, чтобы Instagram успел скачать файлы
                    asyncio.create_task(cleanup_dated_folder(folder_name, delay_seconds=60))

        await asyncio.gather(run_vk(), run_pinterest(), run_instagram())
        await cleanup_carousel(carousel["carousel_id"])

    elif content_type == "VIDEO":
        video_obj = channel_post.get("video") or channel_post.get("animation", {})
        caption   = channel_post.get("caption", "")
        file_id   = video_obj.get("file_id", "")
        file_size = video_obj.get("file_size", 0)
        thumb_obj = video_obj.get("thumbnail") or video_obj.get("thumb")

        # Telegram Bot API: файлы >20 МБ не скачиваются через getFile
        TG_MAX_BYTES = 20 * 1024 * 1024
        if file_size and file_size > TG_MAX_BYTES:
            msg = f"⚠️ Видео слишком большое ({file_size // 1024 // 1024} МБ > 20 МБ), пропускаем"
            print(f"[VIDEO] {msg}")
            await notify_admin(msg)
            return result

        from tools.telegram import resolve_file_id

        print(f"[VIDEO] Скачиваем видео file_id={file_id[:20]}... size={file_size}")
        video_bytes = await resolve_file_id(file_id)
        print(f"[VIDEO] Загружено {len(video_bytes)} байт")

        thumbnail_bytes = None
        if thumb_obj:
            try:
                thumbnail_bytes = await resolve_file_id(thumb_obj["file_id"])
            except Exception as e:
                print(f"[VIDEO] Не удалось скачать превью: {e}")

        async def run_vk_video():
            if not ENABLED_PLATFORMS["vk"]:
                result["platforms"]["vk"] = "disabled"
                return
            try:
                vk_result = await post_video_vk(video_bytes, caption)
                result["platforms"]["vk"] = "ok" if vk_result.get("response") else "error"
                if not vk_result.get("response"):
                    result["errors"].append(f"vk: {vk_result.get('error', 'unknown')}")
            except Exception as e:
                result["platforms"]["vk"] = "error"
                result["errors"].append(f"vk: {str(e)}")

        async def run_instagram_reel():
            if not ENABLED_PLATFORMS["instagram"]:
                result["platforms"]["instagram"] = "disabled"
                return
            folder_name = None
            try:
                if ig_graph_configured():
                    # Graph API: сохраняем видео и обложку в датированную папку
                    folder_name = create_dated_folder()
                    _, video_url, _, cover_url = save_video_with_cover(
                        video_bytes, thumbnail_bytes, folder_name
                    )
                    ig_result = await ig_post_reel(video_url, caption, cover_url)
                else:
                    ig_result = await post_reel_instagram(video_bytes, caption, thumbnail_bytes)
                result["platforms"]["instagram"] = "ok" if ig_result.get("status") == "ok" else "error"
                if ig_result.get("status") != "ok":
                    result["errors"].append(f"instagram: {ig_result.get('reason', 'unknown')}")
            except Exception as e:
                result["platforms"]["instagram"] = "error"
                result["errors"].append(f"instagram: {str(e)}")
            finally:
                if folder_name:
                    # Удаляем папку через 60 сек, чтобы Instagram успел скачать файлы
                    asyncio.create_task(cleanup_dated_folder(folder_name, delay_seconds=60))

        await asyncio.gather(run_vk_video(), run_instagram_reel())

    if result["errors"]:
        result["status"] = "partial" if result["platforms"] else "error"
    else:
        result["status"] = "ok"

    await send_crosspost_notification(channel_post, result)
    return result


async def run_polling():
    """Запуск polling для получения обновлений из Telegram канала"""
    from tools.telegram import start_polling, load_offset
    
    offset = load_offset()
    print(f"Starting polling from offset: {offset}")
    
    async def handle_update(update: dict):
        result = await crosspost(update)
        return result
    
    await start_polling(handle_update, offset)


# ─── Pinterest OAuth ──────────────────────────────────────────────────────────

PINTEREST_APP_ID     = os.getenv("PINTEREST_APP_ID")
PINTEREST_APP_SECRET = os.getenv("PINTEREST_APP_SECRET")
PINTEREST_REDIRECT_URI = os.getenv("PINTEREST_REDIRECT_URI", "")
PINTEREST_TOKEN_FILE = "/root/pinterest_token.json"
PINTEREST_SCOPES = "boards:read,boards:write,pins:read,pins:write,user_accounts:read"


async def homepage(request: Request):
    """Главная страница."""
    return templates.TemplateResponse(request, "index.html", {})


async def privacy_policy(request: Request):
    """Политика конфиденциальности для РФ."""
    return templates.TemplateResponse(request, "privacy.html", {})


async def pinterest_auth(request: Request):
    """Редирект на страницу авторизации Pinterest."""
    if not PINTEREST_APP_ID or not PINTEREST_REDIRECT_URI:
        return HTMLResponse(
            "<h2>❌ Не заданы PINTEREST_APP_ID или PINTEREST_REDIRECT_URI в .env</h2>",
            status_code=500,
        )
    url = (
        f"https://www.pinterest.com/oauth/"
        f"?client_id={PINTEREST_APP_ID}"
        f"&redirect_uri={PINTEREST_REDIRECT_URI}"
        f"&response_type=code"
        f"&scope={PINTEREST_SCOPES}"
    )
    return RedirectResponse(url)


async def pinterest_callback(request: Request):
    """Принимает код от Pinterest, обменивает на токены и сохраняет."""
    import time

    code = request.query_params.get("code")
    error = request.query_params.get("error")

    if error or not code:
        return HTMLResponse(f"<h2>❌ Ошибка авторизации: {error or 'нет кода'}</h2>", status_code=400)

    if not PINTEREST_APP_ID or not PINTEREST_APP_SECRET:
        return HTMLResponse("<h2>❌ Не заданы PINTEREST_APP_ID / PINTEREST_APP_SECRET</h2>", status_code=500)

    credentials = base64.b64encode(f"{PINTEREST_APP_ID}:{PINTEREST_APP_SECRET}".encode()).decode()

    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                "https://api.pinterest.com/v5/oauth/token",
                headers={
                    "Authorization": f"Basic {credentials}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": PINTEREST_REDIRECT_URI,
                },
                timeout=20,
            )
            tokens = r.json()
    except Exception as e:
        return HTMLResponse(f"<h2>❌ Ошибка запроса к Pinterest: {e}</h2>", status_code=500)

    if "access_token" not in tokens:
        return HTMLResponse(f"<h2>❌ Pinterest вернул ошибку: {tokens}</h2>", status_code=400)

    tokens["obtained_at"] = int(time.time())
    with open(PINTEREST_TOKEN_FILE, "w") as f:
        json.dump(tokens, f, indent=2)

    expires_days = tokens.get("expires_in", 0) // 86400
    refresh_days = tokens.get("refresh_token_expires_in", 0) // 86400

    return HTMLResponse(f"""
    <html><body style="font-family:sans-serif;padding:40px">
    <h2>✅ Pinterest авторизован!</h2>
    <p>Токены сохранены на сервере.</p>
    <ul>
      <li>access_token действует <b>{expires_days} дней</b></li>
      <li>refresh_token действует <b>{refresh_days} дней</b></li>
    </ul>
    <p>Бот будет автоматически обновлять токен. Эту страницу можно закрыть.</p>
    </body></html>
    """)


async def _register_webhook():
    """Регистрирует webhook в Telegram при старте сервера."""
    webhook_url = os.getenv("WEBHOOK_URL", "").rstrip("/")
    if not webhook_url:
        print("[WEBHOOK] WEBHOOK_URL не задан — webhook не зарегистрирован")
        return
    target = f"{webhook_url}/webhook"
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"https://api.telegram.org/bot{os.getenv('TELEGRAM_BOT_TOKEN')}/setWebhook",
                json={"url": target, "drop_pending_updates": False, "max_connections": 40},
                timeout=10,
            )
            result = r.json()
        if result.get("ok"):
            print(f"[WEBHOOK] Зарегистрирован: {target}")
        else:
            print(f"[WEBHOOK] Ошибка регистрации: {result}")
    except Exception as e:
        print(f"[WEBHOOK] Не удалось зарегистрировать: {e}")


from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app):
    await _register_webhook()
    async with mcp_app.lifespan(app):
        yield


SITE_MEDIA_DIR = Path(__file__).parent / "site_media"
SITE_MEDIA_DIR.mkdir(parents=True, exist_ok=True)

mcp_app = mcp.http_app(path="/mcp")
app = Starlette(
    routes=[
        Route("/", endpoint=homepage, methods=["GET"]),
        Route("/privacy", endpoint=privacy_policy, methods=["GET"]),
        Mount("/mcp", app=mcp_app),
        Mount("/media", app=StaticFiles(directory=str(MEDIA_DIR)), name="media"),
        Mount("/site_media", app=StaticFiles(directory=str(SITE_MEDIA_DIR)), name="site_media"),
        Route("/webhook", endpoint=webhook_handler, methods=["POST"]),
        Route("/pinterest/auth", endpoint=pinterest_auth, methods=["GET"]),
        Route("/pinterest/callback", endpoint=pinterest_callback, methods=["GET"]),
    ],
    lifespan=lifespan,
)


if __name__ == "__main__":
    import uvicorn

    mode = os.getenv("MODE", "polling")

    if mode == "polling":
        asyncio.run(run_polling())
    else:
        uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")