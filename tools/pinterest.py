import os
import io
import json
import asyncio
import httpx
from PIL import Image
from playwright.async_api import async_playwright

PINTEREST_EMAIL = os.getenv("PINTEREST_EMAIL")
PINTEREST_PASSWORD = os.getenv("PINTEREST_PASSWORD")
PINTEREST_USERNAME = os.getenv("PINTEREST_USERNAME")
PINTEREST_BOARD = os.getenv("PINTEREST_BOARD_NAME")
CRED_ROOT = "/root/crossposting/pinterest_creds"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TOKEN_FILE = "/root/pinterest_token.json"


def load_token() -> str | None:
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE) as f:
            data = json.load(f)
            return data.get("access_token")
    return None


def get_pinterest_client():
    os.makedirs(CRED_ROOT, exist_ok=True)
    cookie_file = os.path.join(CRED_ROOT, "cookies.json")
    token_file = os.path.join(CRED_ROOT, "token.json")

    async def login():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            page = await context.new_page()

            await page.goto("https://www.pinterest.com/login/", wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)

            await page.evaluate(f"""
                document.querySelector('input[type="email"], input[name="email"], input[id="email"]').value = '{PINTEREST_EMAIL}';
                document.querySelector('input[type="password"], input[name="password"], input[id="password"]').value = '{PINTEREST_PASSWORD}';
            """)
            
            await page.locator('button[type="submit"], button[aria-label="Log in"]').first.click()
            await page.wait_for_timeout(5000)

            cookies = await context.cookies()
            with open(cookie_file, "w") as f:
                json.dump(cookies, f)

            storage = await page.evaluate("() => window.localStorage")
            with open(token_file, "w") as f:
                json.dump(storage, f)

            await browser.close()
            return True

    if os.path.exists(cookie_file):
        mtime = os.path.getmtime(cookie_file)
        import time
        if time.time() - mtime < 15 * 24 * 3600:
            return {"status": "using_cached"}

    return asyncio.run(login())


def resize_for_pinterest(image_bytes: bytes) -> bytes:
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    w, h = img.size

    if h >= w:
        target_w, target_h = 1000, 1500
    else:
        target_w, target_h = 1500, 1000

    img.thumbnail((target_w, target_h), Image.LANCZOS)
    canvas = Image.new("RGB", (target_w, target_h), (255, 255, 255))
    offset_x = (target_w - img.width) // 2
    offset_y = (target_h - img.height) // 2
    canvas.paste(img, (offset_x, offset_y))

    output = io.BytesIO()
    canvas.save(output, format="JPEG", quality=95)
    return output.getvalue()


async def adapt_pinterest_text(text: str) -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            json={
                "model": "gpt-4.1-mini",
                "messages": [
                    {"role": "system", "content": (
                        "Из текста создай поля для Pinterest.\n"
                        "TITLE: до 100 символов, цепляющий заголовок\n"
                        "DESC: до 500 символов, описание + 5 хэштегов\n"
                        "Формат строго:\nTITLE: ...\nDESC: ..."
                    )},
                    {"role": "user", "content": text}
                ],
                "temperature": 0.9
            },
            timeout=20
        )
    content = r.json()["choices"][0]["message"]["content"]
    lines = [l for l in content.strip().split("\n") if l.strip()]
    title = lines[0].replace("TITLE:", "").strip()
    desc = lines[1].replace("DESC:", "").strip() if len(lines) > 1 else ""
    return {"title": title, "description": desc}


async def get_board_id_by_name(token: str, board_name: str) -> str | None:
    async with httpx.AsyncClient() as client:
        r = await client.get(
            "https://api.pinterest.com/v5/boards",
            headers={"Authorization": f"Bearer {token}"},
            params={"page_size": 100},
            timeout=15
        )
        boards = r.json().get("items", [])
        for board in boards:
            if board["name"].lower() == board_name.lower():
                return board["id"]
    return None


async def upload_single_image(image_bytes: bytes, token: str) -> str:
    resized = resize_for_pinterest(image_bytes)
    async with httpx.AsyncClient() as client:
        reg = await client.post(
            "https://api.pinterest.com/v5/media",
            headers={"Authorization": f"Bearer {token}"},
            json={"media_type": "image"},
            timeout=15
        )
        data = reg.json()
        upload_url = data["upload_url"]
        media_id = data["media_id"]
        upload_params = data["upload_parameters"]

        files = {"file": ("image.jpg", resized, "image/jpeg")}
        await client.post(upload_url, data=upload_params, files=files, timeout=45)
    return media_id


async def post_single_pin_api(image_bytes: bytes, text: str, token: str, board_id: str) -> dict:
    adapted = await adapt_pinterest_text(text)
    media_id = await upload_single_image(image_bytes, token)

    async with httpx.AsyncClient() as client:
        r = await client.post(
            "https://api.pinterest.com/v5/pins",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            },
            json={
                "board_id": board_id,
                "title": adapted["title"],
                "description": adapted["description"],
                "link": "https://t.me/+jhUtJ494uvtlYjhi",
                "media_source": {
                    "source_type": "media_id",
                    "media_id": media_id
                }
            },
            timeout=20
        )
    return r.json()


async def post_carousel_pin_api(images_bytes: list, text: str, token: str, board_id: str) -> dict:
    adapted = await adapt_pinterest_text(text)
    media_items = []
    for img_bytes in images_bytes[:5]:
        media_id = await upload_single_image(img_bytes, token)
        media_items.append({
            "title": adapted["title"],
            "description": adapted["description"],
            "link": "https://t.me/+jhUtJ494uvtlYjhi",
            "media_id": media_id
        })

    async with httpx.AsyncClient() as client:
        r = await client.post(
            "https://api.pinterest.com/v5/pins",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            },
            json={
                "board_id": board_id,
                "title": adapted["title"],
                "description": adapted["description"],
                "media_source": {
                    "source_type": "multiple_media_ids",
                    "media_ids": [m["media_id"] for m in media_items],
                    "items": media_items
                }
            },
            timeout=30
        )
    return r.json()


async def post_to_pinterest_playwright(images_bytes: list, text: str) -> dict:
    board_name = PINTEREST_BOARD
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        
        cookie_file = os.path.join(CRED_ROOT, "cookies.json")
        if os.path.exists(cookie_file):
            with open(cookie_file) as f:
                cookies = json.load(f)
            await context.add_cookies(cookies)
        
        page = await context.new_page()
        
        await page.goto("https://www.pinterest.com/", wait_until="domcontentloaded", timeout=60000)
        
        if not await page.locator(".App").first.is_visible():
            await page.goto("https://www.pinterest.com/login/", wait_until="domcontentloaded")
            await page.wait_for_timeout(2000)
            await page.locator('input[type="email"], input[name="email"]').first.fill(value=PINTEREST_EMAIL)
            await page.locator('input[type="password"], input[name="password"]').first.fill(value=PINTEREST_PASSWORD)
            await page.locator('button[type="submit"]').first.click()
            await page.wait_for_timeout(5000)
            
            cookies = await context.cookies()
            with open(cookie_file, "w") as f:
                json.dump(cookies, f)
        
        await page.goto(f"https://www.pinterest.com/{PINTEREST_USERNAME}/{board_name.lower()}/", wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(2000)
        
        await page.locator('button[aria-label="Add pin"], .RCk').first.click()
        await page.wait_for_timeout(2000)
        
        for i, img_bytes in enumerate(images_bytes[:5]):
            resized = resize_for_pinterest(img_bytes)
            with open(f"/tmp/pin_{i}.jpg", "wb") as f:
                f.write(resized)
        
        file_input = page.locator('input[type="file"]')
        await file_input.set_input_files([f"/tmp/pin_{i}.jpg" for i in range(len(images_bytes[:5]))])
        await page.wait_for_timeout(3000)
        
        title = text[:100] if len(text) > 100 else text
        await page.locator('textarea[name="title"], input[placeholder*="title"]').first.fill(title)
        
        desc = text[:500] if len(text) > 500 else text
        await page.locator('textarea[name="description"], input[placeholder*="description"]').first.fill(desc)
        
        await page.locator('button:has-text("Save"), button[type="submit"]').first.click()
        await page.wait_for_timeout(5000)
        
        await browser.close()
        
    return {"status": "ok", "method": "playwright"}


async def post_to_pinterest(images_bytes: list, text: str) -> dict:
    """
    Постинг в Pinterest:
    1. Сначала пробуем через API (msp_pinterest)
    2. Если токена нет - используем Playwright
    """
    token = load_token()
    board_name = PINTEREST_BOARD
    
    if token:
        try:
            board_id = await get_board_id_by_name(token, board_name)
            if not board_id:
                return await post_to_pinterest_playwright(images_bytes, text)
            
            if len(images_bytes) == 1:
                result = await post_single_pin_api(images_bytes[0], text, token, board_id)
            else:
                result = await post_carousel_pin_api(images_bytes, text, token, board_id)
            
            return {"status": "ok", "method": "api", "result": result}
        except Exception as e:
            print(f"Pinterest API error: {e}, falling back to playwright")
    
    return await post_to_pinterest_playwright(images_bytes, text)