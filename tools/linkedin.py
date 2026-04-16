import httpx
import os

LINKEDIN_TOKEN = os.getenv("LINKEDIN_TOKEN")
LINKEDIN_AUTHOR = os.getenv("LINKEDIN_AUTHOR_URN")


async def adapt_linkedin(text: str) -> str:
    """GPT адаптирует под LinkedIn: профессиональный тон, до 1300 символов"""
    async with httpx.AsyncClient() as client:
        r = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {os.getenv('OPENAI_API_KEY')}"},
            json={
                "model": "gpt-4.1-mini",
                "messages": [
                    {"role": "system", "content": (
                        "Адаптируй пост для LinkedIn:\n"
                        "- Профессиональный деловой тон\n"
                        "- До 1300 символов\n"
                        "- Первые 2 строки — цепляющий хук\n"
                        "- 3-5 хэштегов в конце\n"
                        "- Добавь ссылку: https://t.me/+jhUtJ494uvtlYjhi\n"
                        "- Без ** и html тегов"
                    )},
                    {"role": "user", "content": text}
                ]
            },
            timeout=20
        )
        return r.json()["choices"][0]["message"]["content"]


async def upload_image_linkedin(image_bytes: bytes) -> str:
    """Загружает изображение и возвращает asset URN"""
    async with httpx.AsyncClient() as client:
        register = await client.post(
            "https://api.linkedin.com/v2/assets?action=registerUpload",
            headers={
                "Authorization": f"Bearer {LINKEDIN_TOKEN}",
                "Content-Type": "application/json",
                "X-Restli-Protocol-Version": "2.0.0"
            },
            json={
                "registerUploadRequest": {
                    "owner": LINKEDIN_AUTHOR,
                    "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
                    "serviceRelationships": [{
                        "identifier": "urn:li:userGeneratedContent",
                        "relationshipType": "OWNER"
                    }]
                }
            },
            timeout=15
        )
        data = register.json()
        upload_url = data["value"]["uploadMechanism"]["com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"]["uploadUrl"]
        asset_urn = data["value"]["asset"]

        await client.put(
            upload_url,
            headers={"Authorization": f"Bearer {LINKEDIN_TOKEN}"},
            content=image_bytes,
            timeout=30
        )
        return asset_urn


async def post_text_linkedin(text: str) -> dict:
    """Текстовый пост в LinkedIn"""
    adapted = await adapt_linkedin(text)
    async with httpx.AsyncClient() as client:
        r = await client.post(
            "https://api.linkedin.com/v2/ugcPosts",
            headers={
                "Authorization": f"Bearer {LINKEDIN_TOKEN}",
                "Content-Type": "application/json",
                "X-Restli-Protocol-Version": "2.0.0"
            },
            json={
                "author": LINKEDIN_AUTHOR,
                "lifecycleState": "PUBLISHED",
                "specificContent": {
                    "com.linkedin.ugc.ShareContent": {
                        "shareCommentary": {"text": adapted},
                        "shareMediaCategory": "NONE"
                    }
                },
                "visibility": {
                    "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
                }
            },
            timeout=20
        )
        return r.json()


async def post_photo_linkedin(image_bytes: bytes, text: str) -> dict:
    """Пост с фото в LinkedIn"""
    adapted = await adapt_linkedin(text)
    asset_urn = await upload_image_linkedin(image_bytes)
    async with httpx.AsyncClient() as client:
        r = await client.post(
            "https://api.linkedin.com/v2/ugcPosts",
            headers={
                "Authorization": f"Bearer {LINKEDIN_TOKEN}",
                "Content-Type": "application/json",
                "X-Restli-Protocol-Version": "2.0.0"
            },
            json={
                "author": LINKEDIN_AUTHOR,
                "lifecycleState": "PUBLISHED",
                "specificContent": {
                    "com.linkedin.ugc.ShareContent": {
                        "shareCommentary": {"text": adapted},
                        "shareMediaCategory": "IMAGE",
                        "media": [{"status": "READY", "media": asset_urn}]
                    }
                },
                "visibility": {
                    "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
                }
            },
            timeout=20
        )
        return r.json()