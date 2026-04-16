import os
import json
import asyncio
from dotenv import load_dotenv
load_dotenv()

import httpx
from fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.routing import Mount, Route
from starlette.requests import Request
from starlette.responses import JSONResponse
from tools.router import detect_type
from tools.telegram import send_message, notify_admin, BASE_URL
from tools.vk import post_text_vk, post_photo_vk
from tools.dzen import post_dzen
from tools.pinterest import post_to_pinterest
from tools.wordstat import get_keywords
from tools.ai_adapter import adapt_vk, adapt_dzen, adapt_youtube
from tools.carousel import process_carousel, cleanup_carousel

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
    if post.get("text"):
        return "TEXT"
    if post.get("media_group_id"):
        return "SLIDES"
    if post.get("photo"):
        return "PHOTO"
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

    msg = f"📤 Кросспостинг\n\nПолучено из канала:\n{preview}\n\n"
    
    success = []
    failed = []
    for platform, status in result.get("platforms", {}).items():
        if status == "ok":
            success.append(platform)
        elif status == "error":
            failed.append(platform)
    
    if success:
        msg += f"✅ Отправлено: {', '.join(success)}\n"
    if failed:
        msg += f"❌ Ошибка: {', '.join(failed)}\n"
    
    if result.get("errors"):
        msg += f"\nОшибки: {result['errors']}"
    
    await notify_admin(msg)


async def webhook_handler(request: Request) -> JSONResponse:
    """Обработка входящих обновлений от Telegram"""
    update = await request.json()
    
    if "channel_post" in update:
        result = await crosspost(update)
        return JSONResponse({"ok": True, "result": result})
    
    return JSONResponse({"ok": True})


carousel_cache = {}
carousel_lock = asyncio.Lock()
pending_carousels = {}
pending_lock = asyncio.Lock()


async def merge_carousel_updates(channel_post: dict) -> dict:
    """Объединяет все части карусели в один пост"""
    import time
    
    media_group_id = channel_post.get("media_group_id")
    
    async with carousel_lock:
        if media_group_id:
            if media_group_id not in carousel_cache:
                carousel_cache[media_group_id] = {"parts": [], "start_time": time.time()}
            carousel_cache[media_group_id]["parts"].append(channel_post)
            return None
        else:
            return channel_post


async def wait_for_carousel(media_group_id: str, timeout: float = 60.0) -> dict:
    """Ожидает полной карусели и возвращает объединённый пост"""
    import time
    
    start = time.time()
    print(f"[MERGE] Waiting for carousel (timeout: {timeout}s)")
    
    while time.time() - start < timeout:
        await asyncio.sleep(2)
        
        async with carousel_lock:
            if media_group_id in carousel_cache:
                parts = carousel_cache[media_group_id]["parts"]
                elapsed = int(time.time() - start)
                print(f"[MERGE] {elapsed}s - buffered {len(parts)} parts")
                
                if elapsed >= timeout:
                    merged = merge_parts(carousel_cache.pop(media_group_id)["parts"])
                    return merged
            else:
                await asyncio.sleep(2)
                async with carousel_lock:
                    if media_group_id in carousel_cache:
                        parts = carousel_cache[media_group_id]["parts"]
                        merged = merge_parts(parts)
                        carousel_cache.pop(media_group_id, None)
                        print(f"[MERGE] Final merge with {len(parts)} parts")
                        return merged
                return None
    
    async with carousel_lock:
        if media_group_id in carousel_cache:
            merged = merge_parts(carousel_cache.pop(media_group_id)["parts"])
            return merged
    return None


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
    """Главный router: определяет тип контента и публикует на всех платформах"""
    result = {"status": "ok", "platforms": {}, "errors": []}
    channel_post = update.get("channel_post", {})
    
    media_group_id = channel_post.get("media_group_id")
    
    if media_group_id:
        merged = await merge_carousel_updates(channel_post)
        if merged is None:
            await asyncio.sleep(0.5)
            merged = await wait_for_carousel(media_group_id)
            if merged is None:
                return {"status": "buffering"}
        channel_post = merged
    
    content_type = detect_content_type(channel_post)
    
    photos = channel_post.get("photo", [])
    file_ids = [p["file_id"] for p in photos]
    print(f"[DEBUG] Total photos in carousel: {len(photos)}, file_ids: {len(set(file_ids))} unique")

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
                adapted = await adapt_youtube(text)
                result["platforms"]["youtube"] = "logged"
            except Exception as e:
                result["errors"].append(f"youtube: {str(e)}")

        await asyncio.gather(run_vk(), run_dzen(), run_youtube())

    elif content_type == "SLIDES":
        photos = channel_post.get("photo", [])
        file_ids = [p["file_id"] for p in photos]
        caption = channel_post.get("caption", "")
        
        carousel = await process_carousel(file_ids)
        
        async def run_vk():
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
                pinterest_result = await post_to_pinterest(carousel["local_paths"], caption)
                result["platforms"]["pinterest"] = "ok"
            except Exception as e:
                result["platforms"]["pinterest"] = "error"
                result["errors"].append(f"pinterest: {str(e)}")

        async def run_dzen():
            if not ENABLED_PLATFORMS["dzen"]:
                result["platforms"]["dzen"] = "disabled"
                return
            try:
                dzen_result = await post_dzen({
                    "urls": carousel["dzen"],
                    "caption": caption
                })
                result["platforms"]["dzen"] = "ok" if dzen_result.get("status") == "ok" else "error"
            except Exception as e:
                result["platforms"]["dzen"] = "error"
                result["errors"].append(f"dzen: {str(e)}")

        await asyncio.gather(run_vk(), run_pinterest(), run_dzen())
        
        await cleanup_carousel(carousel["carousel_id"])
        
        with open("/root/crossposting/last_offset.json", "w") as f:
            json.dump({"offset": 0}, f)

    elif content_type == "PHOTO":
        file_id = channel_post["photo"][-1]["file_id"]
        caption = channel_post.get("caption", "")
        
        carousel = await process_carousel([file_id])
        
        async def run_vk():
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
                pinterest_result = await post_to_pinterest(carousel["local_paths"], caption)
                result["platforms"]["pinterest"] = "ok"
            except Exception as e:
                result["platforms"]["pinterest"] = "error"
                result["errors"].append(f"pinterest: {str(e)}")

        await asyncio.gather(run_vk(), run_pinterest())
        
        await cleanup_carousel(carousel["carousel_id"])

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


mcp_app = mcp.http_app(path="/mcp")
app = Starlette(routes=[
    Mount("/mcp", app=mcp_app),
    Route("/webhook", endpoint=webhook_handler, methods=["POST"]),
], lifespan=mcp_app.lifespan)


if __name__ == "__main__":
    import uvicorn
    
    mode = os.getenv("MODE", "polling")
    
    if mode == "polling":
        asyncio.run(run_polling())
    else:
        uvicorn.run(app, host="0.0.0.0", port=8080)