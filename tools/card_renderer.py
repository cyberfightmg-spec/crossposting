"""Render styled 1080x1080 PNG cards from text (title + body)."""

import io
import textwrap
from PIL import Image, ImageDraw, ImageFont

FONT_BOLD = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
FONT_REGULAR = "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"

SIZE = 1080
PAD = 72

BG_TOP = (15, 15, 35)
BG_BOTTOM = (25, 10, 55)
ACCENT = (99, 102, 241)       # indigo
TITLE_COLOR = (255, 255, 255)
BODY_COLOR = (200, 200, 220)
COUNTER_COLOR = (150, 150, 180)
LINE_COLOR = (99, 102, 241)


def _gradient_bg(draw: ImageDraw.ImageDraw) -> None:
    for y in range(SIZE):
        t = y / SIZE
        r = int(BG_TOP[0] + (BG_BOTTOM[0] - BG_TOP[0]) * t)
        g = int(BG_TOP[1] + (BG_BOTTOM[1] - BG_TOP[1]) * t)
        b = int(BG_TOP[2] + (BG_BOTTOM[2] - BG_TOP[2]) * t)
        draw.line([(0, y), (SIZE, y)], fill=(r, g, b))


def _load(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


def _wrap(text: str, font: ImageFont.FreeTypeFont, max_width: int, draw: ImageDraw.ImageDraw) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        test = (current + " " + word).strip()
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] > max_width and current:
            lines.append(current)
            current = word
        else:
            current = test
    if current:
        lines.append(current)
    return lines


def render_card(
    title: str,
    body: str,
    index: int,
    total: int,
    channel: str = "",
) -> bytes:
    img = Image.new("RGB", (SIZE, SIZE))
    draw = ImageDraw.Draw(img)

    _gradient_bg(draw)

    # Accent bar at top
    draw.rectangle([(PAD, 52), (PAD + 48, 58)], fill=ACCENT)

    # Slide counter
    counter_font = _load(FONT_REGULAR, 32)
    counter_text = f"{index:02d}/{total:02d}"
    draw.text((PAD, 72), counter_text, font=counter_font, fill=COUNTER_COLOR)

    # Channel name (top right)
    if channel:
        ch_font = _load(FONT_REGULAR, 30)
        ch_text = channel if channel.startswith("@") else f"@{channel}"
        bbox = draw.textbbox((0, 0), ch_text, font=ch_font)
        ch_w = bbox[2] - bbox[0]
        draw.text((SIZE - PAD - ch_w, 78), ch_text, font=ch_font, fill=COUNTER_COLOR)

    # Title
    title_font = _load(FONT_BOLD, 68)
    avail = SIZE - PAD * 2
    title_lines = _wrap(title, title_font, avail, draw)
    title_y = 200
    line_h = 84
    for line in title_lines[:4]:
        draw.text((PAD, title_y), line, font=title_font, fill=TITLE_COLOR)
        title_y += line_h

    # Divider
    divider_y = title_y + 24
    draw.rectangle([(PAD, divider_y), (PAD + 64, divider_y + 4)], fill=ACCENT)

    # Body
    body_font = _load(FONT_REGULAR, 40)
    body_y = divider_y + 36
    body_line_h = 56
    body_lines = _wrap(body, body_font, avail, draw)
    max_body_lines = max(1, (SIZE - body_y - PAD - 80) // body_line_h)
    for line in body_lines[:max_body_lines]:
        draw.text((PAD, body_y), line, font=body_font, fill=BODY_COLOR)
        body_y += body_line_h

    # Bottom accent line
    draw.rectangle([(0, SIZE - 8), (SIZE, SIZE)], fill=ACCENT)

    out = io.BytesIO()
    img.save(out, format="PNG", optimize=False)
    return out.getvalue()


def render_cards(slides: list[dict], channel: str = "") -> list[bytes]:
    """Render a list of {title, body} dicts into PNG bytes."""
    total = len(slides)
    return [
        render_card(
            title=s.get("title", ""),
            body=s.get("body", ""),
            index=i + 1,
            total=total,
            channel=channel,
        )
        for i, s in enumerate(slides)
    ]
