"""
Gemini-powered carousel generator.

Слайд 1 — хук (стиль neo.titov.aiblog):
  Oswald-Bold огромный → каждое слово на отдельной строке
  Oswald-Light подзаголовок внизу

Слайды 2+ — контент:
  Oswald-Bold заголовок + Oswald-Light тело текста
"""

import asyncio
import base64
import io
import json
import os
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageFont, ImageFilter

GEMINI_KEY = os.getenv("GEMINI_API_KEY", "")

FONTS_DIR     = Path(__file__).parent.parent / "fonts"
OSWALD_BOLD    = str(FONTS_DIR / "Oswald-Bold.ttf")
OSWALD_LIGHT   = str(FONTS_DIR / "Oswald-Light.ttf")
OSWALD_REGULAR = str(FONTS_DIR / "Oswald-Regular.ttf")

W = H = 1080
PAD = 68


# ─── Step 1: plan slides ──────────────────────────────────────────────────────

async def plan_slides(topic: str, count: int = 5) -> list[dict]:
    """
    Слайд 1: {hook_lines, subtitle, image_prompt}
      hook_lines — массив строк (2-4 слова каждая, всего 2-4 элемента)
      subtitle   — 4-7 слов, объясняет хук
    Слайды 2+: {title, body, image_prompt}
    """
    system = f"""Ты создаёшь план Telegram/Instagram карусели на тему: «{topic}».
Верни JSON-массив из {count} слайдов.

Слайд 1 — ХУКОВЫЙ (обязательная структура):
{{
  "type": "hook",
  "hook_lines": ["СЛОВО", "ИЛИ ДВА", "ЗДЕСЬ"],
  "subtitle": "короткий поясняющий подзаголовок",
  "image_prompt": "English cinematic photo prompt, no text, fits the hook mood"
}}

Правила для hook_lines:
- 2-4 элемента в массиве
- Каждый элемент — 1-3 слова КАПСЛОКОМ или Title Case
- Вместе они образуют цепляющую фразу-хук (как у топовых Reels)
- Примеры хуков: ["ЭТО", "МЕНЯЕТ", "ВСЁ"] / ["НЕТ", "ИДЕЙ?"] / ["ЖИЗНЬ", "КОНЕЧНА"]

Слайды 2-{count} — контентные:
{{
  "type": "content",
  "title": "заголовок до 5 слов",
  "body": "1-2 предложения с главной мыслью",
  "image_prompt": "English cinematic photo prompt, no text"
}}

Верни ТОЛЬКО JSON-массив, без markdown и пояснений."""

    async with httpx.AsyncClient(timeout=45) as client:
        r = await client.post(
            "https://generativelanguage.googleapis.com/v1beta/models/"
            "gemini-2.5-flash-preview-04-17:generateContent?key=" + GEMINI_KEY,
            json={
                "contents": [{"parts": [{"text": system}]}],
                "generationConfig": {
                    "temperature": 0.95,
                    "responseMimeType": "application/json",
                },
            },
        )
    raw = r.json()["candidates"][0]["content"]["parts"][0]["text"]
    try:
        slides = json.loads(raw)
        if isinstance(slides, list):
            return slides
        for v in slides.values():
            if isinstance(v, list):
                return v
    except Exception:
        pass
    return [{"type": "hook", "hook_lines": [topic.upper()], "subtitle": "", "image_prompt": topic}]


# ─── Step 2: generate image ───────────────────────────────────────────────────

async def generate_image(prompt: str) -> bytes:
    async with httpx.AsyncClient(timeout=90) as client:
        r = await client.post(
            "https://generativelanguage.googleapis.com/v1beta/models/"
            "gemini-2.0-flash-preview-image-generation:generateContent?key=" + GEMINI_KEY,
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"responseModalities": ["IMAGE"]},
            },
        )
    data = r.json()
    try:
        for part in data["candidates"][0]["content"]["parts"]:
            if "inlineData" in part:
                return base64.b64decode(part["inlineData"]["data"])
    except Exception:
        pass

    # Fallback: Imagen 3
    try:
        async with httpx.AsyncClient(timeout=90) as client:
            r2 = await client.post(
                "https://generativelanguage.googleapis.com/v1beta/models/"
                "imagen-3.0-generate-002:predict?key=" + GEMINI_KEY,
                json={
                    "instances": [{"prompt": prompt}],
                    "parameters": {"sampleCount": 1, "aspectRatio": "1:1"},
                },
            )
        predictions = r2.json().get("predictions", [])
        if predictions:
            return base64.b64decode(predictions[0]["bytesBase64Encoded"])
    except Exception:
        pass

    return _dark_fallback()


def _dark_fallback() -> bytes:
    img = Image.new("RGB", (W, H), (20, 20, 40))
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


# ─── Step 3: render slides ────────────────────────────────────────────────────

def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


def _draw_text_shadow(
    draw: ImageDraw.ImageDraw,
    xy: tuple,
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: tuple,
    shadow_offset: int = 4,
    shadow_color: tuple = (0, 0, 0, 180),
) -> None:
    """Draw text with a drop shadow."""
    sx, sy = xy[0] + shadow_offset, xy[1] + shadow_offset
    draw.text((sx, sy), text, font=font, fill=shadow_color)
    draw.text(xy, text, font=font, fill=fill)


def _gradient_overlay(img: Image.Image, start_y: int = 300, alpha_bottom: int = 200) -> Image.Image:
    """Add a smooth dark gradient from start_y to bottom."""
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for y in range(start_y, H):
        t = (y - start_y) / (H - start_y)
        a = int(alpha_bottom * (t ** 0.6))
        draw.line([(0, y), (W, y)], fill=(0, 0, 0, a))
    return Image.alpha_composite(img.convert("RGBA"), overlay)


def render_hook_slide(
    bg_bytes: bytes,
    hook_lines: list[str],
    subtitle: str,
    channel: str = "",
) -> bytes:
    """
    Слайд 1: огромный хук (Oswald Bold) + маленький подзаголовок (Oswald Light).
    Стиль neo.titov.aiblog — каждое слово / фраза на отдельной строке.
    """
    bg = Image.open(io.BytesIO(bg_bytes)).convert("RGB").resize((W, H))
    img = _gradient_overlay(bg, start_y=180, alpha_bottom=210)
    draw = ImageDraw.Draw(img)

    # ── Динамический размер хука ──────────────────────────────────────────────
    # Подбираем размер так, чтобы самая длинная строка влезала в ширину
    avail_w = W - PAD * 2
    hook_size = 164
    hook_font = _font(OSWALD_BOLD, hook_size)
    for line in hook_lines:
        while draw.textbbox((0, 0), line, font=hook_font)[2] > avail_w and hook_size > 80:
            hook_size -= 4
            hook_font = _font(OSWALD_BOLD, hook_size)

    line_h = int(hook_size * 1.12)

    # ── Вычисляем позицию блока снизу ─────────────────────────────────────────
    subtitle_size = max(46, hook_size // 3)
    sub_font = _font(OSWALD_LIGHT, subtitle_size)
    total_h = len(hook_lines) * line_h + (subtitle_size + 24 if subtitle else 0)
    start_y = max(160, H - PAD - total_h - 40)

    # ── Рисуем строки хука ────────────────────────────────────────────────────
    y = start_y
    for line in hook_lines:
        _draw_text_shadow(draw, (PAD, y), line, hook_font,
                          fill=(255, 255, 255), shadow_offset=5)
        y += line_h

    # ── Подзаголовок ──────────────────────────────────────────────────────────
    if subtitle:
        y += 8
        _draw_text_shadow(draw, (PAD + 2, y), subtitle, sub_font,
                          fill=(210, 210, 210), shadow_offset=3)

    # ── Канал (верхний правый угол) ───────────────────────────────────────────
    if channel:
        ch = channel if channel.startswith("@") else f"@{channel}"
        ch_font = _font(OSWALD_LIGHT, 30)
        ch_w = draw.textbbox((0, 0), ch, font=ch_font)[2]
        draw.text((W - PAD - ch_w, 36), ch, font=ch_font, fill=(200, 200, 200))

    out = io.BytesIO()
    img.convert("RGB").save(out, format="JPEG", quality=93)
    return out.getvalue()


def render_content_slide(
    bg_bytes: bytes,
    title: str,
    body: str,
    index: int,
    total: int,
    channel: str = "",
) -> bytes:
    """Слайды 2+: заголовок Oswald Bold + тело Oswald Light."""
    bg = Image.open(io.BytesIO(bg_bytes)).convert("RGB").resize((W, H))
    img = _gradient_overlay(bg, start_y=240, alpha_bottom=195)
    draw = ImageDraw.Draw(img)

    avail_w = W - PAD * 2

    # ── Счётчик (верхний левый) ───────────────────────────────────────────────
    cnt_font = _font(OSWALD_REGULAR, 32)
    draw.text((PAD, 38), f"{index}/{total}", font=cnt_font, fill=(180, 180, 180))

    # ── Канал (верхний правый) ────────────────────────────────────────────────
    if channel:
        ch = channel if channel.startswith("@") else f"@{channel}"
        ch_font = _font(OSWALD_LIGHT, 30)
        ch_w = draw.textbbox((0, 0), ch, font=ch_font)[2]
        draw.text((W - PAD - ch_w, 40), ch, font=ch_font, fill=(190, 190, 190))

    # ── Заголовок ─────────────────────────────────────────────────────────────
    title_size = 96
    title_font = _font(OSWALD_BOLD, title_size)
    title_lines = _wrap(draw, title.upper(), title_font, avail_w)
    title_line_h = int(title_size * 1.1)

    # ── Тело текста ───────────────────────────────────────────────────────────
    body_size = 46
    body_font = _font(OSWALD_LIGHT, body_size)
    body_lines = _wrap(draw, body, body_font, avail_w)
    body_line_h = int(body_size * 1.3)

    gap = 20
    total_h = (
        len(title_lines) * title_line_h
        + gap
        + len(body_lines) * body_line_h
    )
    y = max(140, H - PAD - total_h - 30)

    for line in title_lines[:4]:
        _draw_text_shadow(draw, (PAD, y), line, title_font,
                          fill=(255, 255, 255), shadow_offset=4)
        y += title_line_h

    y += gap
    for line in body_lines[:4]:
        _draw_text_shadow(draw, (PAD, y), line, body_font,
                          fill=(215, 215, 215), shadow_offset=2)
        y += body_line_h

    out = io.BytesIO()
    img.convert("RGB").save(out, format="JPEG", quality=93)
    return out.getvalue()


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    words = text.split()
    lines, cur = [], ""
    for word in words:
        test = (cur + " " + word).strip()
        if draw.textbbox((0, 0), test, font=font)[2] > max_w and cur:
            lines.append(cur)
            cur = word
        else:
            cur = test
    if cur:
        lines.append(cur)
    return lines


# ─── Public API ──────────────────────────────────────────────────────────────

async def create_carousel(
    topic: str,
    count: int = 5,
    channel: str = "",
) -> tuple[list[bytes], list[dict]]:
    slides = await plan_slides(topic, count)

    image_bytes = await asyncio.gather(
        *[generate_image(s.get("image_prompt", topic)) for s in slides]
    )

    result: list[bytes] = []
    for i, (bg, slide) in enumerate(zip(image_bytes, slides)):
        if slide.get("type") == "hook" or i == 0:
            result.append(render_hook_slide(
                bg,
                hook_lines=slide.get("hook_lines", [slide.get("title", topic)]),
                subtitle=slide.get("subtitle", ""),
                channel=channel,
            ))
        else:
            result.append(render_content_slide(
                bg,
                title=slide.get("title", ""),
                body=slide.get("body", ""),
                index=i + 1,
                total=len(slides),
                channel=channel,
            ))

    return result, slides
