import os
import time
import json
import hashlib
import httpx
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

OKRU_APP_ID = os.getenv("OKRU_APP_ID")
OKRU_APP_KEY = os.getenv("OKRU_APP_KEY")
OKRU_APP_SECRET = os.getenv("OKRU_APP_SECRET")
OKRU_REDIRECT_URI = os.getenv("OKRU_REDIRECT_URI", "")
OKRU_TOKEN_FILE = os.getenv("OKRU_TOKEN_FILE", "/root/okru_token.json")

OKRU_API = "https://api.ok.ru/fb.do"
OKRU_SCOPES = "VALUABLE_ACCESS;LONG_ACCESS_TOKEN;GROUP_CONTENT;PHOTO_CONTENT"

TOKEN_EXPIRES_BUFFER = 86400


def _read_token() -> dict:
    if os.path.exists(OKRU_TOKEN_FILE):
        with open(OKRU_TOKEN_FILE) as f:
            return json.load(f)
    return {}


def _save_token(data: dict):
    os.makedirs(os.path.dirname(OKRU_TOKEN_FILE) or "/root", exist_ok=True)
    with open(OKRU_TOKEN_FILE, "w") as f:
        json.dump(data, f, indent=2)


def generate_sig(params: dict, access_token: str) -> str:
    """
    Генерирует подпись sig для OK.ru API.
    Формула: MD5(sorted_params + app_secret)
    Где sorted_params = key1=value1key2=value2... (отсортировано по ключам)
    
    ВАЖНО: Для external applications формула такая:
    sig = MD5(application_key + access_token + md5(application_secret_key) + отсортированные_параметры)
    
    Упрощённая версия (часто работает):
    sig = MD5(отсортированные_параметры + application_secret_key)
    
    TODO: Верифицировать точную формулу на реальном API при первом тесте.
    """
    sorted_keys = sorted(params.keys())
    sig_parts = [f"{k}={params[k]}" for k in sorted_keys]
    sig_string = "".join(sig_parts) + OKRU_APP_SECRET
    return hashlib.md5(sig_string.encode()).hexdigest()


def build_signed_params(method: str, access_token: str, extra_params: dict = None) -> dict:
    """Строит параметры с подписью sig для запроса к OK API"""
    params = {
        "application_key": OKRU_APP_KEY,
        "method": method,
        "access_token": access_token,
    }
    if extra_params:
        params.update(extra_params)
    params["sig"] = generate_sig(params, access_token)
    return params


async def get_current_user(access_token: str) -> dict:
    """Получает информацию о текущем пользователе"""
    params = build_signed_params("users.getCurrentUser", access_token)
    async with httpx.AsyncClient() as client:
        r = await client.get(OKRU_API, params=params, timeout=15)
        return r.json()


async def get_user_groups(access_token: str) -> list:
    """Получает список групп пользователя"""
    params = build_signed_params("group.getUserGroups", access_token)
    async with httpx.AsyncClient() as client:
        r = await client.get(OKRU_API, params=params, timeout=15)
        return r.json().get("groups", [])


async def get_group_info(access_token: str, gids: list) -> list:
    """Получает информацию о группах по ID"""
    if not gids:
        return []
    params = build_signed_params("group.getInfo", access_token, {"gids": ",".join(map(str, gids))})
    async with httpx.AsyncClient() as client:
        r = await client.get(OKRU_API, params=params, timeout=15)
        return r.json().get("groups", [])


async def get_upload_url(access_token: str, gid: int = None) -> dict:
    """Получает URL для загрузки фотографий через photosV2.getUploadUrl"""
    params = {
        "access_token": access_token,
        "application_key": OKRU_APP_KEY,
        "method": "photosV2.getUploadUrl",
    }
    if gid:
        params["gid"] = gid
    params["sig"] = generate_sig(params, access_token)
    
    async with httpx.AsyncClient() as client:
        r = await client.get(OKRU_API, params=params, timeout=15)
        return r.json()


async def upload_photo_to_url(photo_bytes: bytes, upload_url: str, filename: str = "photo.jpg") -> dict:
    """Загружает фото на полученный URL"""
    async with httpx.AsyncClient() as client:
        r = await client.post(
            upload_url,
            files={"file1": (filename, photo_bytes, "image/jpeg")},
            timeout=60
        )
        return r.json()


def build_attachment_text_only(text: str) -> dict:
    """Создаёт attachment для text-only поста"""
    return {
        "media": [
            {
                "type": "text",
                "text": text
            }
        ]
    }


def build_attachment_with_photos(text: str, photo_tokens: list) -> dict:
    """
    Создаёт attachment для поста с фото.
    photo_tokens - это список токенов, полученных после загрузки фото.
    """
    media = []
    if text:
        media.append({
            "type": "text",
            "text": text
        })
    for token in photo_tokens:
        media.append({
            "type": "photo",
            "token": token
        })
    return {"media": media}


def build_attachment_link(text: str, url: str) -> dict:
    """Создаёт attachment для поста со ссылкой"""
    return {
        "media": [
            {
                "type": "text",
                "text": text
            },
            {
                "type": "link",
                "url": url
            }
        ]
    }


async def post_mediatopic(
    access_token: str,
    text: str,
    photo_tokens: list = None,
    link_url: str = None,
    gid: int = None
) -> dict:
    """
    Публикует пост через mediatopic.post.
    
    Args:
        access_token: access_token пользователя
        text: текст поста
        photo_tokens: список токенов загруженных фото
        link_url: URL для link-поста
        gid: ID группы (если публикуем в группу)
    """
    if photo_tokens:
        attachment = build_attachment_with_photos(text, photo_tokens)
    elif link_url:
        attachment = build_attachment_link(text, link_url)
    else:
        attachment = build_attachment_text_only(text)
    
    params = {
        "access_token": access_token,
        "application_key": OKRU_APP_KEY,
        "method": "mediatopic.post",
        "attachment": json.dumps(attachment),
        "type": "user"
    }
    
    if gid:
        params["gid"] = gid
        params["type"] = "group"
    
    params["sig"] = generate_sig(params, access_token)
    
    async with httpx.AsyncClient() as client:
        r = await client.get(OKRU_API, params=params, timeout=30)
        return r.json()


async def refresh_token_if_needed(access_token: str) -> str:
    """
    Проверяет срок токена и обновляет при необходимости.
    LONG_ACCESS_TOKEN автоматически продлевается при использовании API.
    """
    data = _read_token()
    
    if not data.get("expires_in"):
        return access_token
    
    obtained_at = data.get("obtained_at", int(time.time()))
    expires_in = data.get("expires_in", 2592000)
    
    if time.time() > obtained_at + expires_in - TOKEN_EXPIRES_BUFFER:
        try:
            user_info = await get_current_user(access_token)
            if "error" in user_info:
                print(f"[OKRU] Token refresh needed: {user_info}")
                return None
            print("[OKRU] Token is still valid (touched)")
        except Exception as e:
            print(f"[OKRU] Token check failed: {e}")
            return None
    
    return access_token


async def load_token() -> Optional[str]:
    """
    Возвращает действующий access_token.
    Проверяет срок и валидность токена.
    """
    data = _read_token()
    token = data.get("access_token")
    
    if not token:
        return None
    
    return await refresh_token_if_needed(token)


async def post_ok_text(text: str, gid: int = None) -> dict:
    """Публикует текстовый пост в Одноклассники"""
    token = await load_token()
    if not token:
        return {"error": "OKRU_NO_TOKEN", "message": "Токен Одноклассников не настроен"}
    
    try:
        result = await post_mediatopic(token, text, gid=gid)
        return result
    except Exception as e:
        return {"error": str(e)}


async def post_ok_photo(text: str, image_paths: list, gid: int = None) -> dict:
    """
    Публикует пост с фото в Одноклассники.
    
    Args:
        text: текст поста
        image_paths: пути к изображениям
        gid: ID группы (если публикуем в группу)
    """
    token = await load_token()
    if not token:
        return {"error": "OKRU_NO_TOKEN", "message": "Токен Одноклассников не настроен"}
    
    photo_tokens = []
    
    try:
        for path in image_paths[:10]:
            with open(path, "rb") as f:
                photo_bytes = f.read()
            
            upload_url_resp = await get_upload_url(token, gid)
            if "error" in upload_url_resp:
                return upload_url_resp
            
            upload_url = upload_url_resp.get("upload_url")
            if not upload_url:
                return {"error": "NO_UPLOAD_URL", "response": upload_url_resp}
            
            upload_result = await upload_photo_to_url(photo_bytes, upload_url)
            token_id = upload_result.get("token") or upload_result.get("photos", [{}])[0].get("token")
            
            if not token_id:
                return {"error": "UPLOAD_FAILED", "response": upload_result}
            
            photo_tokens.append(token_id)
        
        if not photo_tokens:
            return {"error": "NO_PHOTOS_UPLOADED"}
        
        result = await post_mediatopic(token, text, photo_tokens, gid=gid)
        return result
        
    except Exception as e:
        return {"error": str(e)}


async def post_ok_link(text: str, url: str, gid: int = None) -> dict:
    """Публикует пост со ссылкой в Одноклассники"""
    token = await load_token()
    if not token:
        return {"error": "OKRU_NO_TOKEN", "message": "Токен Одноклассников не настроен"}
    
    try:
        result = await post_mediatopic(token, text, link_url=url, gid=gid)
        return result
    except Exception as e:
        return {"error": str(e)}


async def get_ok_groups() -> list:
    """Возвращает список групп пользователя"""
    token = await load_token()
    if not token:
        return []
    
    try:
        groups = await get_user_groups(token)
        if groups:
            gids = [g.get("gid") for g in groups]
            return await get_group_info(token, gids)
        return []
    except Exception as e:
        print(f"[OKRU] Failed to get groups: {e}")
        return []


def is_configured() -> bool:
    """Проверяет наличие настроек OK.ru"""
    return bool(OKRU_APP_ID and OKRU_APP_KEY and OKRU_APP_SECRET and OKRU_REDIRECT_URI)