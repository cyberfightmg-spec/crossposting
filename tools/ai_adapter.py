import os
import httpx
from dotenv import load_dotenv
load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")


async def adapt_vk(text: str) -> str:
    """Adapt text for VK style using Gemini with OpenAI fallback."""
    if GEMINI_API_KEY:
        try:
            async with httpx.AsyncClient() as client:
                r = await client.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent?key={GEMINI_API_KEY}",
                    json={
                        "contents": [{
                            "parts": [{
                                "text": (
                                    f"Ты получаешь пост из Telegram, адаптируй его для ВКонтакте.\n"
                                    "Следуй этим инструкциям:\n"
                                    "- Объем: строго до 1000 символов\n"
                                    "- Сделай красивую отсылку на Телеграмм-канал и добавь ссылку: https://t.me/+jhUtJ494uvtlYjhi\n"
                                    "- Используй минимум эмодзи для структурирования\n"
                                    "- Добавь 3 хэштега в конце\n"
                                    "- Не выделяй текст жирным\n"
                                    "- Не используй **\n"
                                    "- Не используй html теги\n"
                                    f"Пост:\n{text}"
                                )
                            }]
                        }],
                        "generationConfig": {"temperature": 1.0}
                    },
                    timeout=30
                )
                return r.json()["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as e:
            print(f"Gemini error: {e}, falling back to OpenAI")
    
    # OpenAI fallback
    async with httpx.AsyncClient() as client:
        r = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            json={
                "model": "gpt-4.1-mini",
                "messages": [
                    {"role": "system", "content": (
                        "Ты получаешь пост из Telegram, адаптируй его для ВКонтакте.\n"
                        "Следуй этим инструкциям:\n"
                        "- Объем: строго до 1000 символов\n"
                        "- Сделай красивую отсылку на Телеграмм-канал и добавь ссылку: https://t.me/+jhUtJ494uvtlYjhi\n"
                        "- Используй минимум эмодзи для структурирования\n"
                        "- Добавь 3 хэштега в конце\n"
                        "- Не выделяй текст жирным\n"
                        "- Не используй **\n"
                        "- Не используй html теги"
                    )},
                    {"role": "user", "content": f"Пост:\n{text}"}
                ],
                "temperature": 1.0
            },
            timeout=30
        )
        return r.json()["choices"][0]["message"]["content"]


async def adapt_dzen(text: str, keywords: list) -> str:
    """Adapt text for Dzen with SEO."""
    keyword_strings = []
    for kw in keywords[:20]:
        if isinstance(kw, dict):
            keyword_strings.append(kw.get("phrase", str(kw)))
        else:
            keyword_strings.append(str(kw))
    keywords_str = ", ".join(keyword_strings)
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}",
            json={
                "contents": [{
                    "parts": [{
                        "text": (
                            f"Напиши вирусный пост для Яндекс.Дзен в HTML-формате на основе этого материала.\n"
                            f"SEO-ключевые слова для вставки: {keywords_str}\n"
                            f"Правила:\n"
                            f"- До 4000 символов\n"
                            f"- HTML теги: <p>, <b>, <ul>, <li>\n"
                            f"- Вирусный заголовок\n"
                            f"- Добавь ссылку на источник: https://t.me/+jhUtJ494uvtlYjhi\n"
                            f"Материал:\n{text}"
                        )
                    }]
                }],
                "generationConfig": {"temperature": 1.0}
            },
            timeout=45
        )
        return r.json()["candidates"][0]["content"]["parts"][0]["text"]


async def adapt_youtube(text: str) -> str:
    """Adapt text for YouTube description."""
    async with httpx.AsyncClient() as client:
        r = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            json={
                "model": "gpt-4.1-mini",
                "messages": [
                    {"role": "system", "content": (
                        "Адаптируй текст под описание YouTube-видео.\n"
                        "- До 200 слов\n"
                        "- Добавь CTA в конце\n"
                        "- Упомяни канал @leaduxAI\n"
                        "- Без html тегов и звёздочек"
                    )},
                    {"role": "user", "content": text}
                ],
                "temperature": 0.8
            },
            timeout=20
        )
        return r.json()["choices"][0]["message"]["content"]


async def split_into_slides(text: str, max_slides: int = 7) -> list[dict]:
    """Split a long Telegram post into carousel slides via OpenAI.

    Returns a list of {"title": str, "body": str} dicts.
    """
    system = (
        "Ты получаешь пост из Telegram. "
        "Разбей его на карточки для Instagram-карусели.\n"
        "Правила:\n"
        f"- От 3 до {max_slides} карточек\n"
        "- Каждая карточка: title (до 6 слов), body (1-3 предложения)\n"
        "- Ответ ТОЛЬКО в формате JSON-массива:\n"
        '[{"title": "...", "body": "..."}, ...]\n'
        "- Без дополнительного текста, только JSON"
    )
    import json as _json
    async with httpx.AsyncClient() as client:
        r = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            json={
                "model": "gpt-4.1-mini",
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": text},
                ],
                "temperature": 0.7,
                "response_format": {"type": "json_object"},
            },
            timeout=30,
        )
    raw = r.json()["choices"][0]["message"]["content"]
    try:
        parsed = _json.loads(raw)
        if isinstance(parsed, list):
            return parsed
        # Sometimes GPT wraps in {"slides": [...]}
        for v in parsed.values():
            if isinstance(v, list):
                return v
    except Exception:
        pass
    return [{"title": "Пост", "body": text[:300]}]


async def get_wordstat_query(text: str) -> str:
    """GPT generates a broad search query 1-3 words for Wordstat."""
    async with httpx.AsyncClient() as client:
        r = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            json={
                "model": "gpt-4.1-mini",
                "messages": [
                    {"role": "system", "content": "Из текста извлеки главную тему. Верни ТОЛЬКО поисковый запрос из 1-3 слов для Яндекс.Вордстат. Без пояснений."},
                    {"role": "user", "content": text}
                ],
                "temperature": 0.5
            },
            timeout=15
        )
        return r.json()["choices"][0]["message"]["content"].strip()