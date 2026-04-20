import os
import io
import json
import asyncio
import httpx
from PIL import Image
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

SITE_MEDIA_DIR = Path("/root/crossposting/site_media")
SITE_MEDIA_DIR.mkdir(parents=True, exist_ok=True)

KIE_BASE_URL = "https://api.kie.ai"


async def generate_via_kie(prompt: str, output_name: str = "hero", aspect_ratio: str = "16:9") -> str | None:
    """Генерирует изображение через Kie.ai API."""
    api_key = os.getenv("KIE_API_KEY")
    if not api_key:
        print("[KIE] KIE_API_KEY не задан")
        return None
    
    ratio_map = {"16:9": "3:2", "9:16": "2:3", "1:1": "1:1"}
    kie_ratio = ratio_map.get(aspect_ratio, "3:2")
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{KIE_BASE_URL}/api/v1/gpt4o-image/generate",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "prompt": prompt,
                    "size": kie_ratio
                }
            )
            
            if response.status_code != 200:
                print(f"[KIE] Ошибка: {response.status_code} {response.text}")
                return None
            
            result = response.json()
            task_id = result.get("data", {}).get("taskId")
            if not task_id:
                print(f"[KIE] Нет task_id: {result}")
                return None
            
            print(f"[KIE] Task: {task_id}")
            
            for i in range(90):
                await asyncio.sleep(3)
                status_resp = await client.get(
                    f"{KIE_BASE_URL}/api/v1/gpt4o-image/record-info",
                    params={"taskId": task_id},
                    headers={"Authorization": f"Bearer {api_key}"}
                )
                
                if status_resp.status_code != 200:
                    continue
                
                status_data = status_resp.json()
                task_status = status_data.get("data", {}).get("status", "")
                print(f"[KIE] Status: {task_status}")
                
                if task_status == "GENERATING":
                    continue
                
                if task_status == "SUCCESS":
                    result_urls = status_data.get("data", {}).get("response", {}).get("resultUrls", [])
                    if result_urls:
                        img_url = result_urls[0]
                        print(f"[KIE] Downloading: {img_url}")
                        img_resp = await client.get(img_url)
                        if img_resp.status_code == 200:
                            image = Image.open(io.BytesIO(img_resp.content))
                            output_path = SITE_MEDIA_DIR / f"{output_name}.png"
                            image.save(output_path, "PNG")
                            print(f"[KIE] Сохранено: {output_path}")
                            return str(output_path)
                    break
                
                if task_status in ["GENERATE_FAILED", "FAILED"]:
                    print(f"[KIE] Ошибка: {status_data}")
                    return None
            
            print("[KIE] Timeout")
            return None
            
    except Exception as e:
        print(f"[KIE] Exception: {e}")
        return None


async def generate_hero_image(prompt: str, output_name: str = "hero", aspect_ratio: str = "16:9") -> str | None:
    return await generate_via_kie(prompt, output_name, aspect_ratio)


async def generate_site_hero() -> str | None:
    prompt = """Modern tech hero background for dark website. Abstract connected nodes, network visualization, purple #6366f1 and blue #8b5cf6 accents, subtle glow effects, clean professional SaaS style, no text, high quality."""
    return await generate_hero_image(prompt, output_name="hero", aspect_ratio="16:9")


async def generate_platform_icons() -> dict[str, str]:
    platforms = {
        "vk": "VK logo icon, blue #0077FF, minimalist flat design",
        "dzen": "Zen logo, orange #FF6B00, minimalist",
        "pinterest": "Pinterest logo, red #E60023, minimalist",
        "instagram": "Instagram camera logo, gradient pink-orange, minimalist",
        "youtube": "YouTube play button, red #FF0000, minimalist",
    }
    results = {}
    for name, desc in platforms.items():
        path = await generate_hero_image(f"Create {desc}. Square icon.", output_name=f"icon_{name}", aspect_ratio="1:1")
        if path:
            results[name] = path
    return results


async def regenerate_all_site_images() -> dict:
    results = {}
    print("[KIE] Генерация hero...")
    hero = await generate_site_hero()
    results["hero"] = hero
    
    print("[KIE] Генерация иконок...")
    icons = await generate_platform_icons()
    results["icons"] = icons
    
    results["updated_at"] = datetime.now().isoformat()
    return results