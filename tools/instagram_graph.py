import os
import asyncio
import logging
import httpx

log = logging.getLogger("crosspost.instagram_graph")

IG_USER_ID      = os.getenv("INSTAGRAM_USER_ID", "")
IG_ACCESS_TOKEN = os.getenv("INSTAGRAM_GRAPH_TOKEN", "")
IG_API          = "https://graph.instagram.com/v21.0"
OPENAI_KEY      = os.getenv("OPENAI_API_KEY", "")


def is_configured() -> bool:
    return bool(IG_USER_ID and IG_ACCESS_TOKEN)


# ─── Адаптация текста ─────────────────────────────────────────────────────────

async def adapt_caption(text: str) -> str:
    if not text or not text.strip():
        return ""
    try:
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
                        {"role": "user", "content": text},
                    ],
                    "temperature": 0.9,
                },
                timeout=20,
            )
        return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        log.warning(f"Instagram Graph: ошибка адаптации текста — {e}")
        return text


# ─── Вспомогательные функции IG API ───────────────────────────────────────────

async def _create_container(params: dict) -> str:
    """Создаёт медиа-контейнер, возвращает container_id."""
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{IG_API}/{IG_USER_ID}/media",
            data={**params, "access_token": IG_ACCESS_TOKEN},
            timeout=30,
        )
    data = r.json()
    if "error" in data:
        raise Exception(f"IG create container: {data['error'].get('message', data['error'])}")
    log.info(f"Instagram Graph: контейнер создан id={data['id']}")
    return data["id"]


async def _wait_for_video(container_id: str, timeout: int = 300) -> None:
    """Ожидает обработки видео Instagram (polling каждые 10 сек)."""
    async with httpx.AsyncClient() as client:
        for attempt in range(timeout // 10):
            await asyncio.sleep(10)
            r = await client.get(
                f"{IG_API}/{container_id}",
                params={"fields": "status_code,status", "access_token": IG_ACCESS_TOKEN},
                timeout=15,
            )
            data = r.json()
            status = data.get("status_code", "")
            log.info(f"Instagram Graph: статус видео ({attempt + 1}) — {status}")
            if status == "FINISHED":
                return
            if status == "ERROR":
                raise Exception(f"Instagram Graph: ошибка обработки видео: {data.get('status')}")
    raise Exception("Instagram Graph: таймаут обработки видео (>5 мин)")


async def _publish(container_id: str) -> dict:
    """Публикует готовый контейнер."""
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{IG_API}/{IG_USER_ID}/media_publish",
            data={"creation_id": container_id, "access_token": IG_ACCESS_TOKEN},
            timeout=30,
        )
    data = r.json()
    if "error" in data:
        raise Exception(f"IG publish: {data['error'].get('message', data['error'])}")
    return data


# ─── Публикация ───────────────────────────────────────────────────────────────

async def post_photo(image_url: str, caption: str) -> dict:
    """Одиночное фото."""
    adapted = await adapt_caption(caption)
    container_id = await _create_container({"image_url": image_url, "caption": adapted})
    result = await _publish(container_id)
    log.info(f"Instagram Graph фото ✅ id={result.get('id')}")
    return {"status": "ok", "media_id": result.get("id")}


async def post_carousel(image_urls: list, caption: str) -> dict:
    """
    Карусель: создаёт item-контейнер на каждое фото,
    затем объединяет в CAROUSEL и публикует.
    """
    adapted = await adapt_caption(caption)

    # 1. Контейнер для каждого слайда (без caption)
    item_ids = []
    for url in image_urls[:10]:
        item_id = await _create_container({
            "image_url": url,
            "is_carousel_item": "true",
        })
        item_ids.append(item_id)
    log.info(f"Instagram Graph: {len(item_ids)} слайдов подготовлено")

    # 2. Карусельный контейнер
    carousel_id = await _create_container({
        "media_type": "CAROUSEL",
        "children": ",".join(item_ids),
        "caption": adapted,
    })

    # 3. Публикация
    result = await _publish(carousel_id)
    log.info(f"Instagram Graph карусель ✅ id={result.get('id')}")
    return {"status": "ok", "media_id": result.get("id")}


async def post_reel(video_url: str, caption: str, cover_url: str | None = None) -> dict:
    """
    Reel: создаёт контейнер → ждёт обработки видео → публикует.
    Instagram обрабатывает видео асинхронно (обычно 1-3 мин).
    """
    adapted = await adapt_caption(caption)

    params: dict = {
        "media_type": "REELS",
        "video_url": video_url,
        "caption": adapted,
        "share_to_feed": "true",
    }
    if cover_url:
        params["cover_url"] = cover_url

    container_id = await _create_container(params)
    await _wait_for_video(container_id)

    result = await _publish(container_id)
    log.info(f"Instagram Graph Reels ✅ id={result.get('id')}")
    return {"status": "ok", "media_id": result.get("id")}
