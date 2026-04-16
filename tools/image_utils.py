import io
from PIL import Image


def fit_image(
    image_bytes: bytes,
    portrait: tuple = (1000, 1500),
    landscape: tuple = (1500, 1000),
    bg_color: tuple = (255, 255, 255),
    quality: int = 95,
) -> bytes:
    """
    Вписывает изображение в канвас без растяжения.

    Алгоритм:
    - Определяет ориентацию исходного изображения (портрет / пейзаж)
    - Выбирает целевой канвас: portrait=(1000×1500) или landscape=(1500×1000)
    - Масштабирует изображение (вверх или вниз) так, чтобы оно целиком
      поместилось в канвас с сохранением пропорций
    - Центрирует на белом (или заданном) фоне

    Возвращает JPEG-байты.
    """
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    src_w, src_h = img.size

    target_w, target_h = portrait if src_h >= src_w else landscape

    # Масштаб: вписать целиком (не обрезая) — берём минимум по двум осям
    scale = min(target_w / src_w, target_h / src_h)
    new_w = round(src_w * scale)
    new_h = round(src_h * scale)

    img = img.resize((new_w, new_h), Image.LANCZOS)

    canvas = Image.new("RGB", (target_w, target_h), bg_color)
    offset_x = (target_w - new_w) // 2
    offset_y = (target_h - new_h) // 2
    canvas.paste(img, (offset_x, offset_y))

    out = io.BytesIO()
    canvas.save(out, format="JPEG", quality=quality)
    return out.getvalue()
