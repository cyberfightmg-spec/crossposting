# Instagram Media Module - Документация

## Обзор

Модуль реализует хранение фото из Telegram в датированных папках для публикации в Instagram через Graph API.

## Как это работает

### Поток данных

```
Telegram Channel → Скачивание фото → Создание папки (YYYY-MM-DD_HH-MM-SS)
                                              ↓
Instagram Graph API ← Публичный URL ← Сохранение файлов
                                              ↓
                                      Удаление папки (сразу после публикации)
```

### Структура URL

```
https://leaduxai.id/media/2025-04-19_22-30-15/photo1.jpg
\___________________/     \_____________/  \_______/
       Домен              Дата и время      Имя файла
```

## Файлы

### Новые файлы

- **`tools/instagram_media.py`** - Основной модуль с логикой
- **`test_instagram_media.py`** - Тестовый скрипт

### Модифицированные файлы

- **`main.py`** - Обновлена логика публикации в Instagram
- **`.env`** - Добавлен `MEDIA_BASE_URL=https://leaduxai.id`

## Функции модуля instagram_media.py

### `create_dated_folder()` → `str`

Создаёт папку с именем в формате `YYYY-MM-DD_HH-MM-SS`.

**Возвращает:** Имя созданной папки

### `save_photo_to_dated(bytes, folder_name, filename)` → `Tuple[str, str]`

Сохраняет одно фото в датированную папку.

**Параметры:**
- `bytes` - Байты файла
- `folder_name` - Имя папки (от `create_dated_folder()`)
- `filename` - Имя файла (например "photo1.jpg")

**Возвращает:** `(локальный_путь, публичный_url)`

### `save_photos_batch(bytes_list, folder_name)` → `Tuple[List[str], List[str]]`

Сохраняет несколько фото.

**Параметры:**
- `bytes_list` - Список байтов файлов
- `folder_name` - Имя папки

**Возвращает:** `(список_путей, список_url)`

### `save_video_with_cover(video_bytes, cover_bytes, folder_name)` → `Tuple[str, str, str|None, str|None]`

Сохраняет видео и обложку для Reels.

**Возвращает:** `(video_path, video_url, cover_path, cover_url)`

### `cleanup_dated_folder(folder_name)` → `None`

Удаляет папку со всем содержимым после публикации.

## Использование в main.py

### Карусель (несколько фото)

```python
folder_name = create_dated_folder()
photo_bytes_list = [open(p, "rb").read() for p in carousel["local_paths"]]
_, public_urls = save_photos_batch(photo_bytes_list, folder_name)
ig_result = await ig_post_carousel(public_urls, caption)
# ... после публикации ...
cleanup_dated_folder(folder_name)
```

### Одиночное фото

```python
folder_name = create_dated_folder()
photo_bytes = open(carousel["local_paths"][0], "rb").read()
_, public_url = save_photos_batch([photo_bytes], folder_name)
ig_result = await ig_post_photo(public_url[0], caption)
cleanup_dated_folder(folder_name)
```

### Видео (Reels)

```python
folder_name = create_dated_folder()
_, video_url, _, cover_url = save_video_with_cover(
    video_bytes, thumbnail_bytes, folder_name
)
ig_result = await ig_post_reel(video_url, caption, cover_url)
cleanup_dated_folder(folder_name)
```

## Настройка окружения

В `.env` должны быть заданы:

```env
MEDIA_BASE_URL=https://leaduxai.id
MEDIA_DIR=/root/crossposting/media  # опционально, по умолчанию /root/crossposting/media
```

## Безопасность

- Папки создаются с уникальными именами (включая секунды)
- Файлы хранятся только во время публикации
- Сразу после успешной/неуспешной публикации папка удаляется
- Нет накопления старых файлов

## Тестирование

```bash
cd /root/crossposting
python3 test_instagram_media.py
```

## Примеры URL

После публикации фото из поста от 19 апреля 2025 в 22:30:15:

```
https://leaduxai.id/media/2025-04-19_22-30-15/photo1.jpg
https://leaduxai.id/media/2025-04-19_22-30-15/photo2.jpg
https://leaduxai.id/media/2025-04-19_22-30-15/photo3.jpg
```

После успешной публикации все эти файлы автоматически удаляются.
