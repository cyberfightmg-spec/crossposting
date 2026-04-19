#!/usr/bin/env python3
"""
Тестовый скрипт для проверки работы Instagram Media Module
Запуск: python test_instagram_media.py
"""

import sys
import os
sys.path.insert(0, '/root/crossposting')

from tools.instagram_media import (
    create_dated_folder,
    save_photo_to_dated,
    save_photos_batch,
    save_video_with_cover,
    cleanup_dated_folder,
)

print("=" * 60)
print("Тестирование Instagram Media Module")
print("=" * 60)

# Тест 1: Создание папки
print("\n[Тест 1] Создание датированной папки...")
folder_name = create_dated_folder()
print(f"✓ Папка создана: {folder_name}")

# Тест 2: Сохранение одного фото
print("\n[Тест 2] Сохранение одного фото...")
test_photo_bytes = b"fake_photo_bytes_for_testing"  # Заменить на реальные байты при тесте
path, url = save_photo_to_dated(test_photo_bytes, folder_name, "test_photo.jpg")
print(f"✓ Локальный путь: {path}")
print(f"✓ Публичный URL: {url}")

# Тест 3: Сохранение нескольких фото
print("\n[Тест 3] Сохранение нескольких фото...")
test_photos = [b"photo1", b"photo2", b"photo3"]
paths, urls = save_photos_batch(test_photos, folder_name)
print(f"✓ Сохранено фото: {len(paths)}")
for i, u in enumerate(urls):
    print(f"  - URL {i+1}: {u}")

# Тест 4: Сохранение видео и обложки
print("\n[Тест 4] Сохранение видео и обложки...")
video_bytes = b"fake_video_bytes"
cover_bytes = b"fake_cover_bytes"
video_path, video_url, cover_path, cover_url = save_video_with_cover(
    video_bytes, cover_bytes, folder_name
)
print(f"✓ Видео URL: {video_url}")
print(f"✓ Обложка URL: {cover_url}")

# Тест 5: Удаление папки
print("\n[Тест 5] Удаление папки...")
cleanup_dated_folder(folder_name)
print(f"✓ Папка {folder_name} удалена")

print("\n" + "=" * 60)
print("Все тесты пройдены!")
print("=" * 60)
