import httpx
import json
import os
from typing import Union, List

VK_TOKEN = os.getenv("VK_TOKEN")
VK_OWNER_ID = os.getenv("VK_OWNER_ID")
VK_ALBUM_ID = os.getenv("VK_ALBUM_ID")
VK_API = "https://api.vk.com/method"
VK_V = "5.199"


def load_image(path_or_bytes: Union[str, bytes]) -> bytes:
    """Загрузить изображение из пути или байтов"""
    if isinstance(path_or_bytes, bytes):
        return path_or_bytes
    with open(path_or_bytes, "rb") as f:
        return f.read()


async def post_text_vk(text: str) -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.post(f"{VK_API}/wall.post", data={
            "access_token": VK_TOKEN,
            "owner_id": VK_OWNER_ID,
            "message": text,
            "from_group": 1,
            "v": VK_V
        }, timeout=20)
        return r.json()


async def create_album_vk(title: str) -> str:
    """Создать альбом в VK и вернуть album_id"""
    async with httpx.AsyncClient() as client:
        r = await client.post(f"{VK_API}/photos.createAlbum", data={
            "access_token": VK_TOKEN,
            "group_id": VK_OWNER_ID.lstrip("-"),
            "title": title,
            "v": VK_V
        }, timeout=15)
        result = r.json()
        if result.get("response"):
            return result["response"]["id"]
        raise Exception(f"Failed to create album: {result}")


async def upload_photos_to_album(images: List[Union[str, bytes]], album_id: int) -> List[str]:
    """
    Загружает все фото в альбом VK пакетами по 5 штук (лимит VK на один upload-запрос).
    Возвращает список строк вида photo{owner_id}_{id}.
    """
    photo_ids = []
    group_id = VK_OWNER_ID.lstrip("-")
    all_images = images[:10]  # VK wall post: max 10 вложений

    async with httpx.AsyncClient() as client:
        for batch_start in range(0, len(all_images), 5):
            batch = all_images[batch_start:batch_start + 5]

            # 1. Получаем URL для загрузки в альбом
            r = await client.post(f"{VK_API}/photos.getUploadServer", data={
                "access_token": VK_TOKEN,
                "album_id": album_id,
                "group_id": group_id,
                "v": VK_V
            }, timeout=15)
            upload_url = r.json()["response"]["upload_url"]

            # 2. Загружаем весь пакет за один HTTP-запрос (file1, file2, ...)
            files = {}
            for i, img in enumerate(batch):
                img_bytes = load_image(img)
                files[f"file{i + 1}"] = (f"photo_{batch_start + i}.jpg", img_bytes, "image/jpeg")

            upload_res = await client.post(upload_url, files=files, timeout=120)
            upload_data = upload_res.json()
            print(f"[VK] Uploaded batch {batch_start}–{batch_start + len(batch) - 1}: {upload_data}")

            # 3. Сохраняем пакет в альбом
            save_res = await client.post(f"{VK_API}/photos.save", data={
                "access_token": VK_TOKEN,
                "album_id": album_id,
                "group_id": group_id,
                "server": upload_data.get("server", ""),
                "photos_list": upload_data.get("photos_list", ""),
                "hash": upload_data.get("hash", ""),
                "v": VK_V
            }, timeout=15)

            saved = save_res.json()
            print(f"[VK] Saved batch {batch_start}: {saved}")

            if saved.get("response"):
                for p in saved["response"]:
                    photo_ids.append(f'photo{p["owner_id"]}_{p["id"]}')

    return photo_ids


async def post_photo_vk(images: List[Union[str, bytes]], caption: str, carousel: bool = True) -> dict:
    """Загружает все фото в альбом VK, затем публикует один пост со всеми вложениями"""
    album_id = int(VK_ALBUM_ID) if VK_ALBUM_ID else None
    if not album_id:
        return {"error": "VK_ALBUM_ID not set"}

    photo_ids = await upload_photos_to_album(images, album_id)
    if not photo_ids:
        return {"error": "No photos uploaded"}

    async with httpx.AsyncClient() as client:
        r = await client.post(f"{VK_API}/wall.post", data={
            "access_token": VK_TOKEN,
            "owner_id": VK_OWNER_ID,
            "message": caption,
            "attachments": ",".join(photo_ids),
            "from_group": 1,
            "v": VK_V
        }, timeout=20)
        return r.json()


async def post_video_vk(video_bytes: bytes, caption: str) -> dict:
    """Загружает видео в VK и публикует пост со ссылкой на него."""
    group_id = VK_OWNER_ID.lstrip("-")
    async with httpx.AsyncClient() as client:
        # 1. Получаем URL для загрузки
        r = await client.post(f"{VK_API}/video.save", data={
            "access_token": VK_TOKEN,
            "group_id": group_id,
            "name": caption[:100] if caption else "Video",
            "description": caption[:5000] if caption else "",
            "from_group": 1,
            "v": VK_V
        }, timeout=15)
        data = r.json()
        if "error" in data:
            return data
        resp = data["response"]
        upload_url = resp["upload_url"]
        video_id   = resp["video_id"]
        owner_id   = resp["owner_id"]

        # 2. Загружаем файл
        await client.post(
            upload_url,
            files={"video_file": ("video.mp4", video_bytes, "video/mp4")},
            timeout=300,
        )

        # 3. Публикуем пост
        wall_r = await client.post(f"{VK_API}/wall.post", data={
            "access_token": VK_TOKEN,
            "owner_id": VK_OWNER_ID,
            "message": caption,
            "attachments": f"video{owner_id}_{video_id}",
            "from_group": 1,
            "v": VK_V
        }, timeout=20)
        return wall_r.json()


