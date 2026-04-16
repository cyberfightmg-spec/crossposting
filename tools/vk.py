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
    """Загрузить фото в альбом VK и вернуть список photo_ids"""
    import time
    photo_ids = []
    
    for i, img in enumerate(images[:10]):
        async with httpx.AsyncClient() as client:
            upload_server = await client.post(f"{VK_API}/photos.getWallUploadServer", data={
                "access_token": VK_TOKEN,
                "group_id": VK_OWNER_ID.lstrip("-"),
                "v": VK_V
            }, timeout=15)
            
            upload_url = upload_server.json()["response"]["upload_url"]
            img_bytes = load_image(img)
            files = {"photo": (f"img{i}.jpg", img_bytes, "image/jpeg")}
            
            upload_res = await client.post(upload_url, files=files, timeout=60)
            upload_data = upload_res.json()
            print(f"[VK] Upload {i+1}: {upload_data}")
            
            saved = await client.post(f"{VK_API}/photos.saveWallPhoto", data={
                "access_token": VK_TOKEN,
                "group_id": VK_OWNER_ID.lstrip("-"),
                "photo": upload_data.get("photo", ""),
                "server": upload_data.get("server", ""),
                "hash": upload_data.get("hash", ""),
                "v": VK_V
            }, timeout=15)
            
            result = saved.json()
            print(f"[VK] Save {i+1}: {result}")
            
            if result.get("response"):
                p = result["response"][0]
                photo_ids.append(f'photo{p["owner_id"]}_{p["id"]}')
    
    return photo_ids


async def post_photo_vk(images: List[Union[str, bytes]], caption: str, carousel: bool = True) -> dict:
    """Загрузить фото в альбом VK, создать пост со ссылками на фото"""
    album_id = int(VK_ALBUM_ID) if VK_ALBUM_ID else None
    
    if not album_id:
        return {"error": "VK_ALBUM_ID not set"}
    
    photo_ids = await upload_photos_to_album(images, album_id)
    
    async with httpx.AsyncClient() as client:
        data = {
            "access_token": VK_TOKEN,
            "owner_id": VK_OWNER_ID,
            "message": caption,
            "attachments": ",".join(photo_ids),
            "from_group": 1,
            "v": VK_V
        }
        
        if carousel and len(photo_ids) > 1:
            data["primary_attachments_mode"] = "carousel"
        
        r = await client.post(f"{VK_API}/wall.post", data=data, timeout=20)
        return r.json()


async def post_carousel_vk(images: List[Union[str, bytes]], caption: str) -> dict:
    """Пост карусели в VK"""
    return await post_photo_vk(images, caption, carousel=True)