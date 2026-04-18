import os
import time
import json
import httpx

INSTAGRAM_ACCESS_TOKEN = os.getenv("INSTAGRAM_ACCESS_TOKEN")
INSTAGRAM_USER_ID = os.getenv("INSTAGRAM_USER_ID")

BASE = "https://graph.instagram.com/v19.0"
TOKEN_FILE = "/root/crossposting/instagram_token.json"


def save_token(token: str):
    with open(TOKEN_FILE, "w") as f:
        json.dump({"access_token": token, "obtained_at": int(time.time())}, f)


def load_token_from_file() -> str | None:
    if not os.path.exists(TOKEN_FILE):
        return None
    with open(TOKEN_FILE) as f:
        data = json.load(f)
    return data.get("access_token")


async def refresh_long_token(token: str) -> str:
    """Продлевает долгосрочный токен на ещё 60 дней"""
    async with httpx.AsyncClient() as client:
        r = await client.get(
            "https://graph.instagram.com/refresh_access_token",
            params={
                "grant_type": "ig_refresh_token",
                "access_token": token
            }
        )
        data = r.json()
        new_token = data.get("access_token")
        if new_token:
            save_token(new_token)
            print(f"[INSTAGRAM] Token refreshed successfully")
            return new_token
        print(f"[INSTAGRAM] Token refresh failed: {data}")
        return token


async def get_valid_token() -> str:
    """Возвращает токен, автоматически продлевая если осталось меньше 10 дней"""
    token = INSTAGRAM_ACCESS_TOKEN

    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE) as f:
            data = json.load(f)
        obtained_at = data.get("obtained_at", 0)
        saved_token = data.get("access_token")

        days_left = (obtained_at + 60 * 86400 - int(time.time())) / 86400
        print(f"[INSTAGRAM] Token expires in {days_left:.1f} days")

        if days_left < 10:
            print("[INSTAGRAM] Auto-refreshing token...")
            return await refresh_long_token(saved_token)

        return saved_token or token

    save_token(token)
    return token


async def post_photo_instagram(image_url: str, caption: str = "") -> dict:
    token = await get_valid_token()
    async with httpx.AsyncClient() as client:
        r = await client.post(f"{BASE}/{INSTAGRAM_USER_ID}/media", params={
            "image_url": image_url,
            "caption": caption,
            "access_token": token
        })
        data = r.json()
        container_id = data.get("id")
        if not container_id:
            return {"error": data}
        r2 = await client.post(f"{BASE}/{INSTAGRAM_USER_ID}/media_publish", params={
            "creation_id": container_id,
            "access_token": token
        })
        return r2.json()

async def post_carousel_instagram(image_urls: list, caption: str = "") -> dict:
    token = await get_valid_token()
    async with httpx.AsyncClient() as client:
        children = []
        for url in image_urls:
            r = await client.post(f"{BASE}/{INSTAGRAM_USER_ID}/media", params={
                "image_url": url,
                "is_carousel_item": "true",
                "access_token": token
            })
            item_id = r.json().get("id")
            if item_id:
                children.append(item_id)
        r2 = await client.post(f"{BASE}/{INSTAGRAM_USER_ID}/media", params={
            "media_type": "CAROUSEL",
            "children": ",".join(children),
            "caption": caption,
            "access_token": token
        })
        container_id = r2.json().get("id")
        if not container_id:
            return {"error": r2.json()}
        r3 = await client.post(f"{BASE}/{INSTAGRAM_USER_ID}/media_publish", params={
            "creation_id": container_id,
            "access_token": token
        })
        return r3.json()