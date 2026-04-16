import os
import io
import asyncio
import logging
import json
from pathlib import Path
from PIL import Image
from instagrapi import Client
from instagrapi.exceptions import (
    LoginRequired, BadPassword, ChallengeRequired,
    TwoFactorRequired, PleaseWaitFewMinutes, UserNotFound
)

log = logging.getLogger("crosspost.instagram")

IG_USERNAME   = os.getenv("INSTAGRAM_USERNAME")
IG_PASSWORD   = os.getenv("INSTAGRAM_PASSWORD")
IG_SESSION    = "/app/instagram_creds/session.json"
OPENAI_KEY    = os.getenv("OPENAI_API_KEY")

IG_ERRORS = {
    BadPassword:              "❌ Instagram: неверный пароль. Проверь .env",
    ChallengeRequired:        "⚠️ Instagram: требует подтверждение (email/SMS). Зайди вручную и подтверди аккаунт.",
    TwoFactorRequired:        "🔐 Instagram: включена 2FA. Добавь INSTAGRAM_2FA_CODE в .env или отключи 2FA.",
    LoginRequired:            "🔒 Instagram: сессия устарела. Пересоздаю...",
    PleaseWaitFewMinutes:     "⏳ Instagram: слишком много запросов. Подожди 5-10 минут.",
    UserNotFound:             "❓ Instagram: аккаунт не найден. Проверь username.",
}


def _build_client() -> Client:
    cl = Client()
    cl.delay_range = [2, 5]

    session_file = Path(IG_SESSION)
    if session_file.exists():
        try:
            cl.load_settings(IG_SESSION)
            cl.login(IG_USERNAME, IG_PASSWORD)
            log.info("Instagram: сессия восстановлена из файла ✅")
            return cl
        except LoginRequired:
            log.warning("Instagram: сессия устарела, логинимся заново")
            session_file.unlink(missing_ok=True)

    two_fa = os.getenv("INSTAGRAM_2FA_CODE", "")
    if two_fa:
        cl.login(IG_USERNAME, IG_PASSWORD, verification_code=two_fa)
    else:
        cl.login(IG_USERNAME, IG_PASSWORD)

    Path(IG_SESSION).parent.mkdir(parents=True, exist_ok=True)
    cl.dump_settings(IG_SESSION)
    log.info("Instagram: авторизация успешна, сессия сохранена ✅")
    return cl


_ig_client: Client | None = None


async def get_ig_client() -> Client:
    global _ig_client

    try:
        if _ig_client is None:
            loop = asyncio.get_event_loop()
            _ig_client = await loop.run_in_executor(None, _build_client)
        return _ig_client

    except Exception as e:
        _ig_client = None

        user_msg = f"❓ Instagram: неизвестная ошибка — {type(e).__name__}: {e}"
        for exc_type, msg in IG_ERRORS.items():
            if isinstance(e, exc_type):
                user_msg = msg
                break

        log.error(f"Instagram login error: {user_msg}")
        raise Exception(user_msg)


def resize_for_instagram(image_bytes: bytes, mode: str = "square") -> str:
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    w, h = img.size

    if mode == "auto":
        mode = "portrait" if h >= w else "square"

    targets = {"square": (1080, 1080), "portrait": (1080, 1350)}
    tw, th  = targets.get(mode, (1080, 1080))

    img.thumbnail((tw, th), Image.LANCZOS)
    canvas = Image.new("RGB", (tw, th), (255, 255, 255))
    canvas.paste(img, ((tw - img.width) // 2, (th - img.height) // 2))

    path = f"/tmp/ig_{hash(image_bytes)}.jpg"
    canvas.save(path, format="JPEG", quality=95)
    return path


async def get_top_music(cl: Client, keyword: str = "trending") -> str | None:
    try:
        loop = asyncio.get_event_loop()
        tracks = await loop.run_in_executor(
            None, lambda: cl.music_search(keyword, count=10)
        )

        if not tracks:
            tracks = await loop.run_in_executor(
                None, lambda: cl.music_search("popular hits 2025", count=10)
            )

        if tracks:
            track = tracks[0]
            log.info(f"Instagram: трек найден — {track.title} by {track.artist}")
            return str(track.id)

    except Exception as e:
        log.warning(f"Instagram: не удалось получить музыку — {e}")

    return None


async def pick_music_for_content(text: str, cl: Client) -> str | None:
    import httpx
    try:
        async with httpx.AsyncClient() as http:
            r = await http.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {OPENAI_KEY}"},
                json={
                    "model": "gpt-4.1-mini",
                    "messages": [
                        {"role": "system", "content": (
                            "Определи настроение текста и верни ТОЛЬКО "
                            "один короткий музыкальный запрос на английском "
                            "(1-3 слова) для поиска в Instagram музыке. "
                            "Примеры: 'motivational beats', 'chill lofi', "
                            "'upbeat pop', 'corporate success'. Без кавычек."
                        )},
                        {"role": "user", "content": text[:500]}
                    ],
                    "temperature": 0.7
                },
                timeout=10
            )
        keyword = r.json()["choices"][0]["message"]["content"].strip()
        log.info(f"Instagram: музыкальный запрос — '{keyword}'")
        return await get_top_music(cl, keyword)
    except Exception as e:
        log.warning(f"Instagram: ошибка подбора музыки — {e}")
        return await get_top_music(cl)


async def adapt_instagram(text: str) -> str:
    import httpx
    async with httpx.AsyncClient() as client:
        r = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_KEY}"},
            json={
                "model": "gpt-4.1-mini",
                "messages": [
                    {"role": "system", "content": (
                        "Адаптируй текст для Instagram:\n"
                        "- До 2200 символов\n"
                        "- Первые 2 строки — сильный хук (они видны без раскрытия)\n"
                        "- 10-15 хэштегов в конце (релевантных + популярных)\n"
                        "- Добавь ссылку: https://t.me/+jhUtJ494uvtlYjhi\n"
                        "- Эмодзи для структуры\n"
                        "- Без ** и html тегов"
                    )},
                    {"role": "user", "content": text}
                ],
                "temperature": 0.9
            },
            timeout=20
        )
    return r.json()["choices"][0]["message"]["content"]


async def post_photo_instagram(image_bytes: bytes, text: str) -> dict:
    cl      = await get_ig_client()
    caption = await adapt_instagram(text)
    path    = resize_for_instagram(image_bytes, mode="auto")

    loop   = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None, lambda: cl.photo_upload(path, caption=caption)
    )
    log.info(f"Instagram фото ✅ id={result.pk}")
    return {"status": "ok", "media_id": str(result.pk)}


async def post_carousel_instagram(images_bytes: list, text: str) -> dict:
    cl      = await get_ig_client()
    caption = await adapt_instagram(text)

    paths = [resize_for_instagram(img, mode="square") for img in images_bytes[:10]]
    music_id = await pick_music_for_content(text, cl)

    loop = asyncio.get_event_loop()

    if music_id:
        result = await loop.run_in_executor(
            None,
            lambda: cl.album_upload(
                paths,
                caption=caption,
                extra_data={"audio_muted": False, "clips_audio_type": "licensed_music",
                            "music_canonical_id": music_id}
            )
        )
    else:
        result = await loop.run_in_executor(
            None, lambda: cl.album_upload(paths, caption=caption)
        )

    log.info(f"Instagram карусель ✅ id={result.pk} | музыка: {music_id or 'нет'}")
    return {"status": "ok", "media_id": str(result.pk), "music_id": music_id}


async def post_reel_instagram(video_bytes: bytes, text: str,
                               thumbnail_bytes: bytes | None = None) -> dict:
    cl      = await get_ig_client()
    caption = await adapt_instagram(text)
    music_id = await pick_music_for_content(text, cl)

    video_path = f"/tmp/ig_reel_{hash(video_bytes)}.mp4"
    with open(video_path, "wb") as f:
        f.write(video_bytes)

    thumb_path = None
    if thumbnail_bytes:
        thumb_path = resize_for_instagram(thumbnail_bytes, mode="portrait")

    loop = asyncio.get_event_loop()

    extra = {}
    if music_id:
        extra = {"audio_muted": False, "music_canonical_id": music_id}

    result = await loop.run_in_executor(
        None,
        lambda: cl.clip_upload(
            video_path,
            caption=caption,
            thumbnail=thumb_path,
            extra_data=extra if extra else None
        )
    )

    log.info(f"Instagram Reels ✅ id={result.pk} | музыка: {music_id or 'нет'}")
    return {"status": "ok", "media_id": str(result.pk), "music_id": music_id}


async def post_to_instagram(
    images_bytes: list,
    text: str,
    video_bytes: bytes | None = None,
    thumbnail_bytes: bytes | None = None
) -> dict:
    try:
        if video_bytes:
            return await post_reel_instagram(video_bytes, text, thumbnail_bytes)
        elif len(images_bytes) > 1:
            return await post_carousel_instagram(images_bytes, text)
        else:
            return await post_photo_instagram(images_bytes[0], text)
    except Exception as e:
        log.error(f"Instagram ❌: {e}")
        return {"status": "error", "reason": str(e)}