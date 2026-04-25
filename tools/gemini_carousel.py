"""
Gemini-powered carousel generator.

Слайд 1 — хук (стиль neo.titov.aiblog):
  Oswald-Bold огромный, каждое слово на строке + Oswald-Light подзаголовок
  Полноформатное AI-фото на фоне

Слайды 2+ — editorial (стиль mobileeditingclub):
  AI-фото в верхней части (44%)
  Кремовый фон внизу
  Playfair Display Bold + Bold Italic заголовок
  Playfair Display Regular мелкий текст
"""

import asyncio
import base64
import io
import json
import os
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageFont

GEMINI_KEY = os.getenv("GEMINI_API_KEY", "")

FONTS_DIR = Path(__file__).parent.parent / "fonts"
OSWALD_BOLD    = str(FONTS_DIR / "Oswald-Bold.ttf")
OSWALD_LIGHT   = str(FONTS_DIR / "Oswald-Light.ttf")
OSWALD_REGULAR = str(FONTS_DIR / "Oswald-Regular.ttf")
PF_BOLD        = str(FONTS_DIR / "PlayfairDisplay-Bold.ttf")
PF_BOLD_ITALIC = str(FONTS_DIR / "PlayfairDisplay-BoldItalic.ttf")
PF_REGULAR     = str(FONTS_DIR / "PlayfairDisplay-Regular.ttf")

W = H = 1080
PAD = 72

CREAM     = (242, 237, 230)     # тёплый кремовый фон
INK       = (38, 20, 10)        # тёмно-коричневый текст
INK_LIGHT = (110, 90, 75)       # светлый коричневый для body
SPLIT_Y   = 460                 # граница фото / текст на контентных слайдах


# ─── Step 1: plan slides ──────────────────────────────────────────────────────

async def plan_slides(topic: str, count: int = 5) -> list[dict]:
    """
    Слайд 1: {type:"hook", hook_lines, subtitle, image_prompt}
    Слайды 2+: {type:"content", title, body, image_prompt}
      В title слова в *звёздочках* рендерятся курсивом Playfair Bold Italic.
      Пример: "Как это *меняет* всё"
    """
    system = f"""Ты создаёшь план карусели для Telegram/Instagram на тему: «{topic}».
Верни JSON-массив из {count} слайдов.

Слайд 1 — ХУКОВЫЙ (обязательно):
{{
  "type": "hook",
  "hook_lines": ["СЛОВО", "ИЛИ ДВА", "ЗДЕСЬ"],
  "subtitle": "короткий поясняющий подзаголовок",
  "image_prompt": "cinematic photo, no text, relevant to topic"
}}
hook_lines: 2-4 элемента, каждый 1-3 слова, КАПСЛОК, вместе — цепляющий хук.

Слайды 2-{count} — КОНТЕНТНЫЕ:
{{
  "type": "content",
  "title": "Заголовок с *курсивным акцентом*",
  "body": "1-2 предложения — главная мысль слайда.",
  "image_prompt": "editorial photo, no text, clean background, relevant to slide"
}}
В title заключи 1-3 акцентных слова в *звёздочки* — они будут курсивными.
Примеры: "Print-Ready *Marketing Assets*" / "Почему это *работает*" / "*Ключевой* факт о теме"

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
        preds = r2.json().get("predictions", [])
        if preds:
            return base64.b64decode(preds[0]["bytesBase64Encoded"])
    except Exception:
        pass
    return _dark_fallback()


def _dark_fallback() -> bytes:
    img = Image.new("RGB", (W, H), (20, 20, 40))
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


def _shadow(draw, xy, text, font, fill, offset=4, shadow=(0, 0, 0, 160)):
    draw.text((xy[0] + offset, xy[1] + offset), text, font=font, fill=shadow)
    draw.text(xy, text, font=font, fill=fill)


def _wrap(draw, text, font, max_w):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if draw.textbbox((0, 0), t, font=font)[2] > max_w and cur:
            lines.append(cur); cur = w
        else:
            cur = t
    if cur:
        lines.append(cur)
    return lines


def _gradient_overlay(img: Image.Image, start_y=240, alpha_bottom=210) -> Image.Image:
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    for y in range(start_y, H):
        t = (y - start_y) / (H - start_y)
        a = int(alpha_bottom * (t ** 0.55))
        d.line([(0, y), (W, y)], fill=(0, 0, 0, a))
    return Image.alpha_composite(img.convert("RGBA"), overlay)


# ─── Slide 1: hook ────────────────────────────────────────────────────────────

def render_hook_slide(bg_bytes: bytes, hook_lines: list[str],
                      subtitle: str, channel: str = "") -> bytes:
    bg = Image.open(io.BytesIO(bg_bytes)).convert("RGB").resize((W, H))
    img = _gradient_overlay(bg, start_y=180, alpha_bottom=215)
    draw = ImageDraw.Draw(img)

    avail_w = W - PAD * 2
    hook_size = 164
    hook_font = _font(OSWALD_BOLD, hook_size)
    for line in hook_lines:
        while draw.textbbox((0, 0), line, font=hook_font)[2] > avail_w and hook_size > 80:
            hook_size -= 4
            hook_font = _font(OSWALD_BOLD, hook_size)

    line_h = int(hook_size * 1.12)
    subtitle_size = max(44, hook_size // 3)
    sub_font = _font(OSWALD_LIGHT, subtitle_size)
    total_h = len(hook_lines) * line_h + (subtitle_size + 22 if subtitle else 0)
    y = max(160, H - PAD - total_h - 40)

    for line in hook_lines:
        _shadow(draw, (PAD, y), line, hook_font, fill=(255, 255, 255), offset=5)
        y += line_h

    if subtitle:
        y += 8
        _shadow(draw, (PAD + 2, y), subtitle, sub_font, fill=(210, 210, 210), offset=3)

    if channel:
        ch = channel if channel.startswith("@") else f"@{channel}"
        cf = _font(OSWALD_LIGHT, 30)
        cw = draw.textbbox((0, 0), ch, font=cf)[2]
        draw.text((W - PAD - cw, 38), ch, font=cf, fill=(200, 200, 200))

    out = io.BytesIO()
    img.convert("RGB").save(out, format="JPEG", quality=93)
    return out.getvalue()


# ─── Slides 2+: editorial ─────────────────────────────────────────────────────

def _parse_title(title: str) -> list[tuple[str, bool]]:
    """Split "Normal *Italic* Normal" into [(text, is_italic), ...]."""
    parts = title.split("*")
    return [(p, i % 2 == 1) for i, p in enumerate(parts) if p]


def _render_mixed_title(draw, segments, x_start, y, avail_w, max_size=108):
    """
    Render title with mixed Bold / Bold Italic Playfair Display.
    Returns the y position after the last rendered line.
    """
    # Auto-size: find font size where the longest continuous segment fits
    size = max_size
    while size > 52:
        bf = _font(PF_BOLD, size)
        bi = _font(PF_BOLD_ITALIC, size)
        # Check if the whole title fits within avail_w if on one line
        total_w = sum(
            draw.textbbox((0, 0), text, font=(bi if ital else bf))[2]
            for text, ital in segments
        )
        if total_w <= avail_w:
            break
        size -= 4

    bf = _font(PF_BOLD, size)
    bi = _font(PF_BOLD_ITALIC, size)
    line_h = int(size * 1.18)

    # Build word list preserving italic flag per word
    words = []
    for text, ital in segments:
        for w in text.split():
            words.append((w, ital))

    # Word-wrap with font switching
    lines = []
    cur_words = []
    cur_w = 0
    for word, ital in words:
        font = bi if ital else bf
        ww = draw.textbbox((0, 0), word + " ", font=font)[2]
        if cur_w + ww > avail_w and cur_words:
            lines.append(cur_words)
            cur_words = [(word, ital)]
            cur_w = ww
        else:
            cur_words.append((word, ital))
            cur_w += ww
    if cur_words:
        lines.append(cur_words)

    for line_words in lines[:5]:
        x = x_start
        for word, ital in line_words:
            font = bi if ital else bf
            draw.text((x, y), word, font=font, fill=INK)
            x += draw.textbbox((0, 0), word + " ", font=font)[2]
        y += line_h

    return y, size


def render_content_slide(bg_bytes: bytes, title: str, body: str,
                         index: int, total: int, channel: str = "") -> bytes:
    """
    Editorial layout:
      Top SPLIT_Y px  — AI photo (full-width crop)
      Bottom rest     — cream background, Playfair Display headline + body
    """
    # ── Prepare canvas ────────────────────────────────────────────────────────
    canvas = Image.new("RGB", (W, H), CREAM)

    # ── Photo top area ────────────────────────────────────────────────────────
    photo = Image.open(io.BytesIO(bg_bytes)).convert("RGB").resize((W, W))
    # Take a center-top crop
    photo_crop = photo.crop((0, 0, W, SPLIT_Y))
    # Fade bottom of photo into cream
    fade = Image.new("RGBA", (W, SPLIT_Y), (0, 0, 0, 0))
    fd = ImageDraw.Draw(fade)
    fade_start = SPLIT_Y - 120
    for y in range(fade_start, SPLIT_Y):
        t = (y - fade_start) / 120
        a = int(255 * (t ** 1.4))
        r2, g2, b2 = CREAM
        fd.line([(0, y), (W, y)], fill=(r2, g2, b2, a))
    photo_rgba = photo_crop.convert("RGBA")
    photo_faded = Image.alpha_composite(photo_rgba, fade).convert("RGB")
    canvas.paste(photo_faded, (0, 0))

    draw = ImageDraw.Draw(canvas)

    # ── Counter top-right (on photo) ──────────────────────────────────────────
    cf = _font(OSWALD_REGULAR, 28)
    ct = f"{index}/{total}"
    cw = draw.textbbox((0, 0), ct, font=cf)[2]
    draw.text((W - PAD - cw, 32), ct, font=cf, fill=(255, 255, 255, 220))

    # ── Channel name (top-left on photo) ─────────────────────────────────────
    if channel:
        ch = channel if channel.startswith("@") else f"@{channel}"
        chf = _font(OSWALD_LIGHT, 27)
        draw.text((PAD, 34), ch, font=chf, fill=(230, 225, 220))

    # ── Title (Playfair Display Bold + BoldItalic mixed) ─────────────────────
    title_y = SPLIT_Y + 44
    segments = _parse_title(title)
    avail_w = W - PAD * 2

    after_title_y, title_size = _render_mixed_title(
        draw, segments, PAD, title_y, avail_w, max_size=108
    )

    # ── Body text ─────────────────────────────────────────────────────────────
    if body:
        body_size = max(30, title_size // 3)
        body_font = _font(PF_REGULAR, body_size)
        body_lines = _wrap(draw, body, body_font, avail_w)
        by = after_title_y + 20
        for line in body_lines[:3]:
            draw.text((PAD, by), line, font=body_font, fill=INK_LIGHT)
            by += int(body_size * 1.5)

    out = io.BytesIO()
    canvas.save(out, format="JPEG", quality=94)
    return out.getvalue()


# ─── Public API ───────────────────────────────────────────────────────────────

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
