"""
Gemini-powered carousel generator.

Step 1: Gemini 2.5 Flash plans slides → [{title, body, image_prompt}]
Step 2: Gemini image generation creates background PNG for each slide
Step 3: Pillow overlays title + body text on the image
"""

import asyncio
import base64
import io
import json
import os
import textwrap

import httpx
from PIL import Image, ImageDraw, ImageFont

GEMINI_KEY = os.getenv("GEMINI_API_KEY", "")

FONT_BOLD    = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
FONT_REGULAR = "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"

SLIDE_W, SLIDE_H = 1080, 1080


# ─── Step 1: plan slides ──────────────────────────────────────────────────────

async def plan_slides(topic: str, count: int = 5) -> list[dict]:
    """Ask Gemini 2.5 Flash to break a topic into carousel slide plans."""
    system = (
        f"Ты создаёшь план для Instagram/Telegram-карусели на тему: «{topic}».\n"
        f"Сделай ровно {count} слайдов.\n"
        "Каждый слайд — JSON-объект:\n"
        '{"title":"...", "body":"...", "image_prompt":"..."}\n'
        "- title: до 5 слов, цепляющий заголовок\n"
        "- body: 1-2 предложения с главной мыслью\n"
        "- image_prompt: English prompt for an AI image generator (no text on image).\n"
        "  Style: cinematic, clean, minimalist, relevant to the slide topic.\n"
        "Верни ТОЛЬКО JSON-массив, без лишнего текста."
    )
    async with httpx.AsyncClient(timeout=40) as client:
        r = await client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"gemini-2.5-flash-preview-04-17:generateContent?key={GEMINI_KEY}",
            json={
                "contents": [{"parts": [{"text": system}]}],
                "generationConfig": {"temperature": 0.9, "responseMimeType": "application/json"},
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
    return [{"title": topic, "body": "", "image_prompt": topic}]


# ─── Step 2: generate image via Gemini ───────────────────────────────────────

async def generate_image(prompt: str) -> bytes:
    """Generate an image via Gemini imagen / flash image generation.

    Returns raw PNG/JPEG bytes, or a solid-color fallback if generation fails.
    """
    async with httpx.AsyncClient(timeout=90) as client:
        r = await client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"gemini-2.0-flash-preview-image-generation:generateContent?key={GEMINI_KEY}",
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"responseModalities": ["IMAGE"]},
            },
        )
    data = r.json()
    try:
        parts = data["candidates"][0]["content"]["parts"]
        for part in parts:
            if "inlineData" in part:
                return base64.b64decode(part["inlineData"]["data"])
    except Exception:
        pass

    # Fallback: try Imagen 3
    try:
        async with httpx.AsyncClient(timeout=90) as client:
            r2 = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"imagen-3.0-generate-002:predict?key={GEMINI_KEY}",
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

    return _solid_fallback()


def _solid_fallback() -> bytes:
    """Return a dark gradient PNG as fallback when image generation fails."""
    img = Image.new("RGB", (SLIDE_W, SLIDE_H))
    draw = ImageDraw.Draw(img)
    for y in range(SLIDE_H):
        t = y / SLIDE_H
        r = int(15 + 10 * t)
        g = int(15 + 5 * t)
        b = int(35 + 20 * t)
        draw.line([(0, y), (SLIDE_W, y)], fill=(r, g, b))
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


# ─── Step 3: overlay text on image ───────────────────────────────────────────

def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


def _wrap_text(draw, text: str, font, max_w: int) -> list[str]:
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


def _overlay_text(
    bg_bytes: bytes,
    title: str,
    body: str,
    index: int,
    total: int,
    channel: str = "",
) -> bytes:
    """Paste title + body over the background image, with a semi-transparent bar."""
    bg = Image.open(io.BytesIO(bg_bytes)).convert("RGBA").resize((SLIDE_W, SLIDE_H))

    # Dark overlay at the bottom half for readability
    overlay = Image.new("RGBA", (SLIDE_W, SLIDE_H), (0, 0, 0, 0))
    ov_draw = ImageDraw.Draw(overlay)
    ov_draw.rectangle([(0, 480), (SLIDE_W, SLIDE_H)], fill=(0, 0, 0, 180))
    # Top gradient bar
    ov_draw.rectangle([(0, 0), (SLIDE_W, 100)], fill=(0, 0, 0, 120))
    combined = Image.alpha_composite(bg, overlay).convert("RGB")

    draw = ImageDraw.Draw(combined)
    pad = 64
    avail = SLIDE_W - pad * 2

    # Counter (top-left)
    cnt_font = _font(FONT_REGULAR, 30)
    draw.text((pad, 36), f"{index:02d}/{total:02d}", font=cnt_font, fill=(200, 200, 255))

    # Channel (top-right)
    if channel:
        ch = channel if channel.startswith("@") else f"@{channel}"
        ch_font = _font(FONT_REGULAR, 28)
        w = draw.textbbox((0, 0), ch, font=ch_font)[2]
        draw.text((SLIDE_W - pad - w, 38), ch, font=ch_font, fill=(180, 180, 220))

    # Accent line above title
    draw.rectangle([(pad, 510), (pad + 56, 516)], fill=(99, 102, 241))

    # Title
    title_font = _font(FONT_BOLD, 64)
    title_lines = _wrap_text(draw, title, title_font, avail)
    ty = 528
    for line in title_lines[:3]:
        draw.text((pad, ty), line, font=title_font, fill=(255, 255, 255))
        ty += 78

    # Body
    if body:
        body_font = _font(FONT_REGULAR, 38)
        body_lines = _wrap_text(draw, body, body_font, avail)
        ty += 8
        for line in body_lines[:3]:
            draw.text((pad, ty), line, font=body_font, fill=(210, 210, 230))
            ty += 52

    out = io.BytesIO()
    combined.save(out, format="JPEG", quality=92)
    return out.getvalue()


# ─── Public API ──────────────────────────────────────────────────────────────

async def create_carousel(
    topic: str,
    count: int = 5,
    channel: str = "",
) -> tuple[list[bytes], list[dict]]:
    """Full pipeline: topic → slides plan → Gemini images → text overlay.

    Returns (jpeg_bytes_list, slides_metadata).
    """
    slides = await plan_slides(topic, count)

    # Generate all background images in parallel
    image_bytes = await asyncio.gather(
        *[generate_image(s.get("image_prompt", topic)) for s in slides]
    )

    result_images = [
        _overlay_text(
            bg,
            title=s.get("title", ""),
            body=s.get("body", ""),
            index=i + 1,
            total=len(slides),
            channel=channel,
        )
        for i, (bg, s) in enumerate(zip(image_bytes, slides))
    ]

    return result_images, slides
