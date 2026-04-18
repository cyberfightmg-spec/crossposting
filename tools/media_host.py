import os
import uuid
import shutil
import logging
from pathlib import Path

log = logging.getLogger("crosspost.media_host")

MEDIA_DIR      = Path(os.getenv("MEDIA_DIR", "/root/crossposting/media"))
MEDIA_BASE_URL = os.getenv("MEDIA_BASE_URL", "").rstrip("/")

MEDIA_DIR.mkdir(parents=True, exist_ok=True)


def _check_base_url():
    if not MEDIA_BASE_URL:
        raise RuntimeError("MEDIA_BASE_URL не задан в .env (например: https://leaduxai.id)")


def save_media(data: bytes, ext: str = "jpg") -> tuple[str, str]:
    """Сохраняет байты в media-папку, возвращает (локальный_путь, публичный_url)."""
    _check_base_url()
    filename = f"{uuid.uuid4().hex}.{ext}"
    path = MEDIA_DIR / filename
    path.write_bytes(data)
    url = f"{MEDIA_BASE_URL}/media/{filename}"
    log.info(f"Медиафайл сохранён: {url}")
    return str(path), url


def copy_to_media(local_path: str) -> tuple[str, str]:
    """Копирует существующий файл в media-папку, возвращает (новый_путь, публичный_url)."""
    _check_base_url()
    ext = Path(local_path).suffix.lstrip(".") or "jpg"
    filename = f"{uuid.uuid4().hex}.{ext}"
    new_path = MEDIA_DIR / filename
    shutil.copy2(local_path, new_path)
    url = f"{MEDIA_BASE_URL}/media/{filename}"
    log.info(f"Медиафайл скопирован: {url}")
    return str(new_path), url


def delete_media(*paths: str) -> None:
    """Удаляет один или несколько файлов из media-папки."""
    for path in paths:
        try:
            Path(path).unlink(missing_ok=True)
            log.info(f"Медиафайл удалён: {path}")
        except Exception as e:
            log.warning(f"Не удалось удалить {path}: {e}")
