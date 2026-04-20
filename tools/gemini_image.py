import os
import io
import httpx
from PIL import Image
from google import genai
from google.genai import types

client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

GEMINI_MODEL = "gemini-2.5-flash-image"


async def generate_image(prompt: str, aspect_ratio: str = "16:9") -> bytes | None:
    """
    Генерирует изображение через Gemini 2.5 Flash Image.
    
    Args:
        prompt: текстовое описание изображения
        aspect_ratio: соотношение сторон (1:1, 3:2, 2:3, 3:4, 4:3, 4:5, 5:4, 9:16, 16:9, 21:9)
    
    Returns:
        bytes изображения или None при ошибке
    """
    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE"],
                image_config=types.ImageConfig(
                    aspect_ratio=aspect_ratio
                )
            )
        )
        
        for part in response.candidates[0].content.parts:
            if part.inline_data is not None:
                return part.inline_data.data
        
        return None
        
    except Exception as e:
        print(f"[GEMINI] Ошибка генерации: {e}")
        return None


async def edit_image(prompt: str, image_bytes: bytes) -> bytes | None:
    """
    Редактирует изображение через Gemini.
    
    Args:
        prompt: инструкция по изменению
        bytes исходного изображения
    
    Returns:
        bytes изменённого изображения или None
    """
    try:
        input_image = Image.open(io.BytesIO(image_bytes))
        
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[prompt, input_image],
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE"],
                image_config=types.ImageConfig(
                    aspect_ratio="16:9"
                )
            )
        )
        
        for part in response.candidates[0].content.parts:
            if part.inline_data is not None:
                return part.inline_data.data
        
        return None
        
    except Exception as e:
        print(f"[GEMINI] Ошибка редактирования: {e}")
        return None


async def generate_og_image(title: str, platform: str = "vk") -> bytes:
    """
    Генерирует OG-картинку для поста.
    
    Args:
        title: заголовок поста
        platform: целевая платформа (vk, dzen, pinterest, instagram, youtube)
    
    Returns:
        bytes изображения
    """
    platform_styles = {
        "vk": "VK style - blue gradient, modern social network banner",
        "dzen": "Дзен style - orange accent, article preview card",
        "pinterest": "Pinterest style - red accent, pin board aesthetic",
        "instagram": "Instagram style - modern gradient, mobile-first",
        "youtube": "YouTube style - red accent, video thumbnail",
    }
    
    style = platform_styles.get(platform, "modern social media banner")
    
    prompt = f"""
    Create a modern social media post preview image for "{title}".
    Style: {style}.
    
    Requirements:
    - Clean modern design
    - Bold typography for the title
    - Platform-appropriate color scheme
    - Professional looking, suitable for public content
    - No text in the image, just visual design
    - Aspect ratio 16:9
    - High quality, crisp details
    """
    
    image_bytes = await generate_image(prompt.strip(), "16:9")
    
    if image_bytes is None:
        raise Exception("Failed to generate image")
    
    return image_bytes