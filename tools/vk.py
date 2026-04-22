import httpx
import json
import os
import io
import subprocess
import tempfile
from typing import Union, List
from PIL import Image, ImageDraw, ImageFont
from dotenv import load_dotenv

load_dotenv()

VK_TOKEN = os.getenv("VK_TOKEN")
VK_USER_TOKEN = os.getenv("VK_USER_TOKEN") or os.getenv("VK_TOKEN")
VK_OWNER_ID = os.getenv("VK_OWNER_ID")
VK_ALBUM_ID = os.getenv("VK_ALBUM_ID")
VK_USER_ID = os.getenv("VK_USER_ID")
VK_API = "https://api.vk.com/method"
VK_V = "5.199"

WATERMARK_TEXT = "vk.ru/leadux_ai"
VIDEO_WATERMARK_TEXT = "leaduxai"


def add_watermark_to_image(image_data: bytes) -> bytes:
    """Добавляет водяной знак vc.com/leadux_ai на изображение"""
    img = Image.open(io.BytesIO(image_data))
    
    width, height = img.size
    
    draw = ImageDraw.Draw(img)
    
    font_size = max(int(height * 0.03), 20)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
    except Exception:
        font = ImageFont.load_default()
    
    try:
        bbox = draw.textbbox((0, 0), WATERMARK_TEXT, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
    except Exception:
        text_width = len(WATERMARK_TEXT) * font_size * 0.6
        text_height = font_size
    
    x = (width - text_width) // 2
    y = height - text_height - int(height * 0.05)
    
    img = img.convert('RGBA')
    
    draw = ImageDraw.Draw(img)
    draw.text((x, y), WATERMARK_TEXT, fill=(255, 255, 255, 128), font=font)
    
    img = img.convert('RGB')
    
    output = io.BytesIO()
    img.save(output, format='JPEG', quality=95)
    output.seek(0)
    return output.read()


def add_watermark_to_video(video_bytes: bytes, watermark_text: str = VIDEO_WATERMARK_TEXT, opacity: float = 0.15) -> bytes:
    """Добавляет текстовый водяной знак на видео с указанной прозрачностью.
    
    Args:
        video_bytes: исходное видео в байтах
        watermark_text: текст водяного знака
        opacity: непрозрачность (0.15 = 15% = 85% прозрачность)
    
    Returns:
        видео с водяным знаком в байтах
    """
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp_in:
        tmp_in.write(video_bytes)
        tmp_in_path = tmp_in.name
    
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp_out:
        tmp_out_path = tmp_out.name
    
    try:
        font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if not os.path.exists(font_path):
            font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        
        filter_cmd = (
            f"drawtext=fontfile='{font_path}':"
            f"text='{watermark_text}':"
            f"fontcolor=white@{opacity}:"
            f"fontsize=h/15:"
            f"x=(w-text_w)/2:"
            f"y=(h-text_h)*0.95:"
            f"borderw=1:"
            f"bordercolor=black@{opacity}:"
            f"alpha={opacity}"
        )
        
        cmd = [
            "ffmpeg", "-y",
            "-i", tmp_in_path,
            "-vf", filter_cmd,
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-c:a", "copy",
            tmp_out_path
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=300
        )
        
        if result.returncode != 0:
            print(f"[WATERMARK] ffmpeg error: {result.stderr.decode()[:500]}")
            return video_bytes
        
        with open(tmp_out_path, "rb") as f:
            return f.read()
    
    finally:
        for p in [tmp_in_path, tmp_out_path]:
            try:
                os.unlink(p)
            except:
                pass


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
    print(f"[VIDEO] Adding watermark to video ({len(video_bytes)} bytes)...")
    video_bytes = add_watermark_to_video(video_bytes)
    print(f"[VIDEO] Watermark added, new size: {len(video_bytes)} bytes")
    
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


async def post_story_vk(image_bytes: bytes, caption: str = "") -> dict:
    """Публикует сторис в группу VK с водяным знаком"""
    import sys
    print(f"[STORY] Starting story upload...", flush=True)
    print(f"[STORY] VK_OWNER_ID={VK_OWNER_ID}", flush=True)
    print(f"[STORY] VK_USER_ID={VK_USER_ID}", flush=True)
    
    story_owner_id = VK_OWNER_ID
    if not story_owner_id:
        print(f"[STORY] ERROR: No VK_OWNER_ID set")
        return {"error": "VK_OWNER_ID not set"}
    
    story_token = VK_USER_TOKEN
    if not story_token:
        print(f"[STORY] ERROR: No VK_USER_TOKEN set, cannot post story")
        return {"error": "VK_USER_TOKEN not set"}
    
    group_id = abs(int(VK_OWNER_ID))
    print(f"[STORY] Using owner_id: {story_owner_id} (group_id: {group_id})")
    print(f"[STORY] Using USER token for story API")
    
    watermarked = add_watermark_to_image(image_bytes)
    print(f"[STORY] Watermark added, size: {len(watermarked)} bytes")
    
    async with httpx.AsyncClient() as client:
        # 1. Получаем URL для загрузки сторис в группу
        print(f"[STORY] Getting upload server...")
        r = await client.post(f"{VK_API}/stories.getPhotoUploadServer", data={
            "access_token": story_token,
            "owner_id": story_owner_id,
            "add_to_news": 1,
            "v": VK_V
        }, timeout=15)
        data = r.json()
        print(f"[STORY] Step 1 response: {data}")
        
        if "error" in data:
            print(f"[STORY] ERROR: Upload server error: {data}")
            return data
        
        upload_url = data["response"]["upload_url"]
        
        # 2. Загружаем фото
        print(f"[STORY] Uploading photo...")
        upload_res = await client.post(
            upload_url,
            files={"photo": ("story.jpg", watermarked, "image/jpeg")},
            timeout=60
        )
        upload_data = upload_res.json()
        print(f"[STORY] Step 2 response: {upload_data}")
        
        if "error" in upload_data:
            print(f"[STORY] ERROR: Upload error: {upload_data}")
            return upload_data
        
        # 3. Сохраняем сторис
        print(f"[STORY] Saving story...")
        save_res = await client.post(f"{VK_API}/stories.save", data={
            "access_token": story_token,
            "upload_results": upload_data["response"]["upload_result"],
            "v": VK_V
        }, timeout=15)
        
        result = save_res.json()
        print(f"[STORY] Final result: {result}")
        return result


