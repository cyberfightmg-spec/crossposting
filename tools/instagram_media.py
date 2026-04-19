"""
Instagram Media Storage Module

Сохраняет фото из Telegram в датированные папки для Instagram Graph API.
Использует публичный URL вида: https://leaduxai.id/media/2025-04-19_22-30-15/photo1.jpg
"""

import os
import shutil
import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Tuple, List

log = logging.getLogger("crosspost.instagram_media")

# Путь к директории для медиа
MEDIA_DIR = Path(os.getenv("MEDIA_DIR", "/root/crossposting/media"))
BASE_URL = os.getenv("MEDIA_BASE_URL", "https://leaduxai.id").rstrip("/")


def _ensure_media_dir():
    """Создаёт корневую media директорию если не существует."""
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)


def create_dated_folder() -> str:
    """
    Создаёт папку с названием в формате YYYY-MM-DD_HH-MM-SS.
    
    Returns:
        str: Имя созданной папки (например "2025-04-19_22-30-15")
    """
    _ensure_media_dir()
    folder_name = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    folder_path = MEDIA_DIR / folder_name
    folder_path.mkdir(parents=True, exist_ok=True)
    log.info(f"[INSTAGRAM_MEDIA] Создана папка: {folder_path}")
    return folder_name


def save_photo_to_dated(
    file_bytes: bytes,
    folder_name: str,
    filename: str
) -> Tuple[str, str]:
    """
    Сохраняет фото в датированную папку.
    
    Args:
        file_bytes: Байты файла
        folder_name: Имя папки (от create_dated_folder)
        filename: Имя файла (например "photo1.jpg")
    
    Returns:
        Tuple[str, str]: (локальный_путь, публичный_url)
    """
    folder_path = MEDIA_DIR / folder_name
    folder_path.mkdir(parents=True, exist_ok=True)
    
    file_path = folder_path / filename
    file_path.write_bytes(file_bytes)
    
    public_url = f"{BASE_URL}/media/{folder_name}/{filename}"
    log.info(f"[INSTAGRAM_MEDIA] Файл сохранён: {public_url}")
    return str(file_path), public_url


def save_photos_batch(
    file_bytes_list: List[bytes],
    folder_name: str,
    extension: str = "jpg"
) -> Tuple[List[str], List[str]]:
    """
    Сохраняет несколько фото в датированную папку.
    
    Args:
        file_bytes_list: Список байтов файлов
        folder_name: Имя папки
        extension: Расширение файлов
    
    Returns:
        Tuple[List[str], List[str]]: (список_путей, список_url)
    """
    local_paths = []
    public_urls = []
    
    for i, file_bytes in enumerate(file_bytes_list):
        filename = f"photo{i+1}.{extension}"
        local_path, public_url = save_photo_to_dated(file_bytes, folder_name, filename)
        local_paths.append(local_path)
        public_urls.append(public_url)
    
    return local_paths, public_urls


def save_video_with_cover(
    video_bytes: bytes,
    cover_bytes: bytes | None,
    folder_name: str
) -> Tuple[str, str, str | None, str | None]:
    """
    Сохраняет видео и обложку для Reels.
    
    Args:
        video_bytes: Байты видео
        cover_bytes: Байты обложки (или None)
        folder_name: Имя папки
    
    Returns:
        Tuple: (video_path, video_url, cover_path, cover_url)
    """
    # Сохраняем видео
    video_path, video_url = save_photo_to_dated(video_bytes, folder_name, "video.mp4")
    
    # Сохраняем обложку если есть
    cover_path = None
    cover_url = None
    if cover_bytes:
        cover_path, cover_url = save_photo_to_dated(cover_bytes, folder_name, "cover.jpg")
    
    return video_path, video_url, cover_path, cover_url


async def cleanup_dated_folder(folder_name: str, delay_seconds: int = 60) -> None:
    """
    Удаляет датированную папку со всем содержимым.
    Добавляет задержку перед удалением, чтобы Instagram успел скачать файлы.
    
    Args:
        folder_name: Имя папки для удаления
        delay_seconds: Задержка в секундах перед удалением (по умолчанию 60)
    """
    if delay_seconds > 0:
        log.info(f"[INSTAGRAM_MEDIA] Ожидание {delay_seconds} сек перед удалением папки {folder_name}...")
        await asyncio.sleep(delay_seconds)
    
    folder_path = MEDIA_DIR / folder_name
    if folder_path.exists():
        shutil.rmtree(folder_path)
        log.info(f"[INSTAGRAM_MEDIA] Папка удалена: {folder_path}")
    else:
        log.warning(f"[INSTAGRAM_MEDIA] Папка не найдена: {folder_path}")
