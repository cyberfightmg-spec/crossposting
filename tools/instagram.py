import os
import io
import asyncio
import logging
from pathlib import Path
from PIL import Image
from instagrapi import Client
from instagrapi.exceptions import (
    LoginRequired, BadPassword, ChallengeRequired,
    TwoFactorRequired, PleaseWaitFewMinutes, UserNotFound
)
from tools.image_utils import fit_image

log = logging.getLogger("crosspost.instagram")

IG_USERNAME = os.getenv("INSTAGRAM_USERNAME")
IG_PASSWORD = os.getenv("INSTAGRAM_PASSWORD")
IG_SESSION  = os.getenv("INSTAGRAM_SESSION", "/root/crossposting/instagram_creds/session.json")
OPENAI_KEY  = os.getenv("OPENAI_API_KEY")

IG_ERRORS = {
    BadPassword:          "❌ Instagram: неверный пароль. Проверь .env",
    ChallengeRequired:    "⚠️ Instagram: требует подтверждение (email/SMS). Зайди вручную.",
    TwoFactorRequired:    "🔐 Instagram: включена 2FA. Добавь INSTAGRAM_2FA_CODE в .env.",
    LoginRequired:        "🔒 Instagram: сессия устарела. Пересоздаю...",
    PleaseWaitFewMinutes: "⏳ Instagram: слишком много запросов. Подожди 5-10 минут.",
    UserNotFound:         "❓ Instagram: аккаунт не найден. Проверь username.",
}


def _fresh_client() -> Client:
    cl = Client()
    cl.delay_range = [2, 5]
    return cl


def _do_login(cl: Client) -> Client:
    """Выполняет логин и сохраняет сессию."""
    two_fa = os.getenv("INSTAGRAM_2FA_CODE", "")
    if two_fa:
        cl.login(IG_USERNAME, IG_PASSWORD, verification_code=two_fa)
    else:
        cl.login(IG_USERNAME, IG_PASSWORD)
    Path(IG_SESSION).parent.mkdir(parents=True, exist_ok=True)
    cl.dump_settings(IG_SESSION)
    log.info("Instagram: авторизация успешна, сессия сохранена ✅")
    return cl


def _build_client() -> Client:
    session_file = Path(IG_SESSION)

    if session_file.exists():
        try:
            cl = _fresh_client()
            cl.load_settings(IG_SESSION)         # загружаем device fingerprint
            cl.login(IG_USERNAME, IG_PASSWORD)   # обновляем токен
            log.info("Instagram: сессия восстановлена из файла ✅")
            return cl
        except LoginRequired:
            log.warning("Instagram: сессия устарела, пересоздаём клиент")
            session_file.unlink(missing_ok=True)
            # cl намеренно не переиспользуем — создаём чистый объект ниже
        except Exception as e:
            log.warning(f"Instagram: ошибка загрузки сессии ({e}), логинимся заново")
            session_file.unlink(missing_ok=True)

    # Свежий логин без старых настроек
    return _do_login(_fresh_client())


_ig_client: Client | None = None


async def get_ig_client() -> Client:
    global _ig_client
    if _ig_client is None:
        loop = asyncio.get_event_loop()
        try:
            _ig_client = await loop.run_in_executor(None, _build_client)
        except Exception as e:
            _ig_client = None
            user_msg = f"❓ Instagram: {type(e).__name__}: {e}"
            for exc_type, msg in IG_ERRORS.items():
                if isinstance(e, exc_type):
                    user_msg = msg
                    break
            log.error(user_msg)
            raise Exception(user_msg)
    return _ig_client


async def _run_with_relogin(fn):
    """
    Запускает fn() в executor. При LoginRequired сбрасывает сессию и повторяет один раз.
    """
    global _ig_client
    loop = asyncio.get_event_loop()
    try:
        return await loop.run_in_executor(None, fn)
    except LoginRequired:
        log.warning("Instagram: LoginRequired во время постинга — пересоздаём сессию")
        _ig_client = None
        Path(IG_SESSION).unlink(missing_ok=True)
        _ig_client = await loop.run_in_executor(None, _build_client)
        return await loop.run_in_executor(None, fn)


# ─── Ресайз ───────────────────────────────────────────────────────────────────

def resize_for_instagram(image_bytes: bytes, mode: str = "square") -> str:
    """
    Подгоняет изображение под Instagram без растяжения.
    mode='square'   → 1080×1080  (для карусели — все слайды одного размера)
    mode='portrait' → 1080×1350  (4:5, одиночные фото)
    mode='auto'     → portrait если h>=w, иначе square
    """
    if mode == "auto":
        tmp = Image.open(io.BytesIO(image_bytes))
        mode = "portrait" if tmp.height >= tmp.width else "square"

    if mode == "portrait":
        resized = fit_image(image_bytes, portrait=(1080, 1350), landscape=(1080, 1080))
    else:
        # square: и портреты и пейзажи → 1080×1080
        resized = fit_image(image_bytes, portrait=(1080, 1080), landscape=(1080, 1080))

    path = f"/tmp/ig_{abs(hash(image_bytes))}.jpg"
    with open(path, "wb") as f:
        f.write(resized)
    return path


# ─── Музыка ───────────────────────────────────────────────────────────────────

def _track_artist(track) -> str:
    """Возвращает имя артиста из MusicTrack (поле называется subtitle, не artist)."""
    return (
        getattr(track, "subtitle", None)
        or getattr(track, "artist", None)
        or getattr(track, "display_artist", None)
        or "Unknown"
    )


async def get_top_music(cl: Client, keyword: str = "trending") -> str | None:
    """
    Ищет трек в Instagram по ключевому слову, возвращает music_id или None.
    Пробует несколько запросов по убыванию специфичности.
    """
    if not hasattr(cl, "music_search"):
        log.warning("Instagram: music_search не поддерживается — обновите instagrapi")
        return None

    loop = asyncio.get_event_loop()
    queries = [keyword, "popular hits 2025", "top hits", "trending music"]
    # убираем дубли, сохраняя порядок
    seen: set = set()
    unique_queries = [q for q in queries if not (q in seen or seen.add(q))]

    for query in unique_queries:
        try:
            tracks = await loop.run_in_executor(
                None, lambda q=query: cl.music_search(q, count=10)
            )
            if tracks:
                track = tracks[0]
                artist = _track_artist(track)
                music_id = str(track.id)
                log.info(f"Instagram: трек — '{track.title}' by '{artist}' id={music_id}")
                return music_id
            log.warning(f"Instagram: music_search({query!r}) вернул пустой список")
        except Exception as e:
            log.warning(f"Instagram: music_search({query!r}) — {type(e).__name__}: {e}")

    log.warning("Instagram: не удалось найти трек, публикуем без музыки")
    return None


async def pick_music_for_content(text: str, cl: Client) -> str | None:
    """GPT определяет жанр/настроение → ищет трек в Instagram."""
    import httpx
    if not text or not text.strip():
        return await get_top_music(cl)
    try:
        async with httpx.AsyncClient() as http:
            r = await http.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {OPENAI_KEY}"},
                json={
                    "model": "gpt-4.1-mini",
                    "messages": [
                        {"role": "system", "content": (
                            "Определи настроение текста и верни ТОЛЬКО один "
                            "короткий музыкальный запрос на английском (1-3 слова) "
                            "для поиска в Instagram. Примеры: 'motivational beats', "
                            "'chill lofi', 'upbeat pop', 'corporate success'. Без кавычек."
                        )},
                        {"role": "user", "content": text[:500]}
                    ],
                    "temperature": 0.7,
                },
                timeout=10,
            )
        keyword = r.json()["choices"][0]["message"]["content"].strip()
        log.info(f"Instagram: музыкальный запрос от GPT — '{keyword}'")
        music_id = await get_top_music(cl, keyword)
        if music_id:
            return music_id
        # GPT-запрос не дал результата — пробуем общий
        log.warning("Instagram: GPT-запрос не дал трека, пробуем 'trending'")
        return await get_top_music(cl)
    except Exception as e:
        log.warning(f"Instagram: ошибка подбора музыки через GPT — {e}")
        return await get_top_music(cl)


# ─── Адаптация текста ─────────────────────────────────────────────────────────

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
                        "- Первые 2 строки — сильный хук\n"
                        "- 10-15 хэштегов в конце\n"
                        "- Эмодзи для структуры\n"
                        "- Без ** и html тегов"
                    )},
                    {"role": "user", "content": text}
                ],
                "temperature": 0.9,
            },
            timeout=20,
        )
    return r.json()["choices"][0]["message"]["content"]


# ─── Публикация ───────────────────────────────────────────────────────────────

async def post_photo_instagram(image_bytes: bytes, text: str) -> dict:
    cl      = await get_ig_client()
    caption = await adapt_instagram(text)
    path    = resize_for_instagram(image_bytes, mode="auto")

    result = await _run_with_relogin(lambda: cl.photo_upload(path, caption=caption))
    log.info(f"Instagram фото ✅ id={result.pk}")
    return {"status": "ok", "media_id": str(result.pk)}


async def post_carousel_instagram(images_bytes: list, text: str) -> dict:
    """
    Публикует карусель (album) в Instagram.
    Все слайды приводятся к 1080×1080 (square).
    Музыка не поддерживается в album_upload через приватный API —
    для музыки используй post_reel_instagram.
    """
    cl      = await get_ig_client()
    caption = await adapt_instagram(text)

    paths = [resize_for_instagram(img, mode="square") for img in images_bytes[:10]]
    log.info(f"Instagram: подготовлено {len(paths)} слайдов")

    result = await _run_with_relogin(
        lambda: cl.album_upload(paths, caption=caption)
    )

    log.info(f"Instagram карусель ✅ id={result.pk}")
    return {"status": "ok", "media_id": str(result.pk)}


async def post_reel_instagram(
    video_bytes: bytes, text: str, thumbnail_bytes: bytes | None = None
) -> dict:
    cl       = await get_ig_client()
    caption  = await adapt_instagram(text)
    music_id = await pick_music_for_content(text, cl)

    video_path = f"/tmp/ig_reel_{abs(hash(video_bytes))}.mp4"
    with open(video_path, "wb") as f:
        f.write(video_bytes)

    thumb_path = None
    if thumbnail_bytes:
        thumb_path = resize_for_instagram(thumbnail_bytes, mode="portrait")

    # extra_data для clip_upload: музыка прикрепляется через clips_audio_type
    extra_data = None
    if music_id:
        extra_data = {
            "audio_muted": False,
            "clips_audio_type": "licensed_music",
            "music_canonical_id": music_id,
        }
        log.info(f"Instagram Reels: прикрепляем music_id={music_id}")
    else:
        log.warning("Instagram Reels: музыка не найдена, публикуем без трека")

    result = await _run_with_relogin(
        lambda: cl.clip_upload(
            video_path,
            caption=caption,
            thumbnail=thumb_path,
            extra_data=extra_data,
        )
    )

    log.info(f"Instagram Reels ✅ id={result.pk} | музыка: {music_id or 'нет'}")
    return {"status": "ok", "media_id": str(result.pk), "music_id": music_id}


# ─── Главная точка входа ──────────────────────────────────────────────────────

async def post_to_instagram(
    image_paths: list,
    text: str,
    video_bytes: bytes | None = None,
    thumbnail_bytes: bytes | None = None,
) -> dict:
    """
    image_paths — список локальных путей к файлам.
    """
    try:
        if video_bytes:
            return await post_reel_instagram(video_bytes, text, thumbnail_bytes)

        images_bytes = [open(p, "rb").read() for p in image_paths]

        if len(images_bytes) > 1:
            return await post_carousel_instagram(images_bytes, text)
        else:
            return await post_photo_instagram(images_bytes[0], text)
    except Exception as e:
        log.error(f"Instagram ❌: {e}")
        return {"status": "error", "reason": str(e)}
