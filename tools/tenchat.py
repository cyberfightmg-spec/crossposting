"""
Tenchat API - Playwright-based automation for posting to tenchat.ru
Вход по телефону с SMS-подтверждением + storage_state для сессии
"""
import os
import json
import asyncio
from pathlib import Path
from typing import Optional, List, Union
from playwright.async_api import async_playwright
from dotenv import load_dotenv

load_dotenv()

TENCHAT_PHONE = os.getenv("TENCHAT_PHONE", "79169547408")
TENCHAT_STATE_FILE = Path(__file__).parent.parent / "tenchat_session.json"


def has_credentials() -> bool:
    """Check if Tenchat phone is configured."""
    return bool(TENCHAT_PHONE)


class TenchatAgent:
    """Async agent for posting to Tenchat using Playwright."""
    
    def __init__(self, headless: bool = True):
        self.headless = headless
        self.browser = None
        self.context = None
        self.page = None
        self.playwright = None
    
    async def start(self):
        """Initialize browser and context with saved session if exists."""
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=self.headless,
            args=['--no-sandbox', '--disable-setuid-sandbox']
        )
        
        # Load storage state if exists
        if TENCHAT_STATE_FILE.exists():
            print("[TENCHAT] Loading saved session...")
            self.context = await self.browser.new_context(
                storage_state=str(TENCHAT_STATE_FILE),
                viewport={"width": 1920, "height": 1080}
            )
        else:
            self.context = await self.browser.new_context(
                viewport={"width": 1920, "height": 1080}
            )
        
        self.page = await self.context.new_page()
    
    async def stop(self):
        """Close browser and cleanup."""
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
    
    async def _save_session(self):
        """Save storage state to file."""
        await self.context.storage_state(path=str(TENCHAT_STATE_FILE))
        print(f"[TENCHAT] Session saved to {TENCHAT_STATE_FILE}")
    
    async def is_logged_in(self) -> bool:
        """Check if currently logged in."""
        try:
            # Идём на главную и смотрим куда редиректнет
            await self.page.goto("https://tenchat.ru", wait_until="domcontentloaded", timeout=10000)
            await asyncio.sleep(2)
            
            current_url = self.page.url
            print(f"[TENCHAT] Current URL: {current_url}")
            
            # Если на странице входа - не авторизованы
            if "/auth" in current_url or "/login" in current_url:
                print("[TENCHAT] On login page - not logged in")
                return False
            
            # Если на главной или feed - авторизованы
            if current_url in ["https://tenchat.ru/", "https://tenchat.ru", "https://tenchat.ru/feed"]:
                print("[TENCHAT] On feed page - logged in")
                return True
            
            # Проверяем наличие элементов ленты
            feed_selectors = [
                '[data-testid="feed"]',
                '.feed',
                '[data-testid="create-post"]',
                '.post-creator',
                'button:has-text("Написать")',
                'a[href="/feed"]'
            ]
            
            for selector in feed_selectors:
                try:
                    element = await self.page.wait_for_selector(selector, timeout=2000)
                    if element:
                        print(f"[TENCHAT] Found feed element: {selector}")
                        return True
                except:
                    continue
            
            print(f"[TENCHAT] No feed elements found - probably not logged in")
            return False
            
        except Exception as e:
            print(f"[TENCHAT] Error checking login status: {e}")
            return False
    
    async def login(self) -> bool:
        """Login to Tenchat via phone with SMS verification."""
        print(f"[TENCHAT] Checking login status...")
        
        # Load session if exists
        if TENCHAT_STATE_FILE.exists():
            print(f"[TENCHAT] Found session file: {TENCHAT_STATE_FILE}")
        
        # Check if already logged in via saved session
        if await self.is_logged_in():
            print("[TENCHAT] Already logged in via saved session")
            await self._save_session()  # Refresh session
            return True
        
        print(f"[TENCHAT] Not logged in, session may be expired")
        print(f"[TENCHAT] Please re-login via browser manually")
        return False
        await asyncio.sleep(3)
        
        try:
            # Find phone input
            print("[TENCHAT] Looking for phone input...")
            phone_input = await self.page.wait_for_selector(
                'input[type="tel"], input[name="phone"], input[placeholder*="телефон"]', 
                timeout=5000
            )
            
            # Fill phone
            phone_formatted = f"+{TENCHAT_PHONE}"
            await phone_input.fill(phone_formatted)
            await asyncio.sleep(0.5)
            print(f"[TENCHAT] Phone filled: {phone_formatted}")
            
            # Click submit
            submit_btn = await self.page.wait_for_selector(
                'button[type="submit"], button:has-text("Продолжить"), button:has-text("Получить код")',
                timeout=5000
            )
            await submit_btn.click()
            print("[TENCHAT] Waiting for SMS code input...")
            
            # Wait for SMS code field
            await asyncio.sleep(2)
            code_input = await self.page.wait_for_selector(
                'input[name="code"], input[type="text"][inputmode="numeric"], input[placeholder*="код"]',
                timeout=10000
            )
            
            if code_input:
                print("\n" + "="*50)
                print("[TENCHAT] ВВЕДИТЕ КОД ИЗ SMS!")
                print("[TENCHAT] У тебя 60 секунд...")
                print("="*50 + "\n")
                
                # Wait for manual code entry
                await asyncio.sleep(60)
                
                # Check if login successful
                if await self.is_logged_in():
                    await self._save_session()
                    print("[TENCHAT] Login successful!")
                    return True
                else:
                    print("[TENCHAT] Login failed after code entry")
                    return False
            else:
                print("[TENCHAT] Code input not found")
                return False
                
        except Exception as e:
            print(f"[TENCHAT] Login error: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def post_text(self, text: str, title: str = "") -> dict:
        """Post text to Tenchat."""
        try:
            await self.page.goto("https://tenchat.ru/feed")
            await asyncio.sleep(2)
            
            # Click create post button
            create_btn = await self.page.wait_for_selector(
                'button:has-text("Написать"), [data-testid="create-post"], .post-creator',
                timeout=5000
            )
            await create_btn.click()
            await asyncio.sleep(1)
            
            # Fill title if provided
            if title:
                title_input = await self.page.query_selector('input[placeholder*="заголовок"], input[name="title"]')
                if title_input:
                    await title_input.fill(title)
                    await asyncio.sleep(0.5)
            
            # Fill text
            text_input = await self.page.wait_for_selector(
                'div[contenteditable="true"], textarea[placeholder*="текст"], textarea',
                timeout=5000
            )
            await text_input.fill(text)
            await asyncio.sleep(1)
            
            # Publish
            publish_btn = await self.page.wait_for_selector(
                'button:has-text("Опубликовать"), button[type="submit"]',
                timeout=5000
            )
            await publish_btn.click()
            await asyncio.sleep(3)
            
            return {"status": "ok", "platform": "tenchat", "type": "text"}
            
        except Exception as e:
            print(f"[TENCHAT] Error posting text: {e}")
            return {"status": "error", "error": str(e)}
    
    async def post_photo(self, image_paths: List[Union[str, bytes]], caption: str = "", title: str = "") -> dict:
        """Post photo(s) to Tenchat."""
        print(f"[TENCHAT] Starting photo post, images: {len(image_paths)}")
        try:
            # Проверяем текущий URL - возможно мы уже на нужной странице
            current_url = self.page.url
            print(f"[TENCHAT] Current URL before goto: {current_url}")
            
            if "tenchat.ru" not in current_url:
                print("[TENCHAT] Navigating to feed...")
                await self.page.goto("https://tenchat.ru/feed", wait_until="commit", timeout=10000)
            else:
                print("[TENCHAT] Already on tenchat, refreshing...")
                await self.page.reload(wait_until="commit", timeout=10000)
            
            print("[TENCHAT] On feed page")
            await asyncio.sleep(5)  # Ждём загрузку JS
            
            # Click create post - пробуем разные селекторы
            print("[TENCHAT] Looking for create post button...")
            create_btn = None
            for selector in [
                'button:has-text("Написать")',
                'a:has-text("Написать")',
                '[data-testid="create-post"]',
                '.post-creator',
                'button svg',  # кнопка с иконкой
            ]:
                try:
                    create_btn = await self.page.wait_for_selector(selector, timeout=3000)
                    if create_btn:
                        print(f"[TENCHAT] Found button: {selector}")
                        break
                except:
                    continue
            
            if not create_btn:
                print("[TENCHAT] ERROR: Could not find create post button")
                # Делаем скриншот для диагностики
                await self.page.screenshot(path="/root/crossposting/tenchat_debug.png")
                return {"status": "error", "error": "Create post button not found"}
            print("[TENCHAT] Clicking create post button")
            await create_btn.click()
            await asyncio.sleep(1)
            
            # Fill title if provided
            if title:
                print("[TENCHAT] Filling title...")
                title_input = await self.page.query_selector('input[placeholder*="заголовок"], input[name="title"]')
                if title_input:
                    await title_input.fill(title)
                    await asyncio.sleep(0.5)
            
            # Fill caption
            if caption:
                print("[TENCHAT] Filling caption...")
                text_input = await self.page.wait_for_selector(
                    'div[contenteditable="true"], textarea',
                    timeout=10000
                )
                await text_input.fill(caption)
                await asyncio.sleep(0.5)
            
            # Upload images
            print("[TENCHAT] Uploading images...")
            file_input = await self.page.wait_for_selector(
                'input[type="file"][accept*="image"]',
                timeout=10000
            )
            
            for i, img_path in enumerate(image_paths):
                print(f"[TENCHAT] Uploading image {i+1}/{len(image_paths)}...")
                if isinstance(img_path, bytes):
                    import tempfile
                    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
                        f.write(img_path)
                        tmp_path = f.name
                    await file_input.set_input_files(tmp_path)
                    os.unlink(tmp_path)
                else:
                    await file_input.set_input_files(img_path)
                await asyncio.sleep(1)
            
            await asyncio.sleep(2)
            
            # Publish
            print("[TENCHAT] Clicking publish button...")
            publish_btn = await self.page.wait_for_selector('button:has-text("Опубликовать")', timeout=5000)
            await publish_btn.click()
            await asyncio.sleep(3)
            
            print("[TENCHAT] Photo posted successfully!")
            return {"status": "ok", "platform": "tenchat", "type": "photo"}
            
        except Exception as e:
            print(f"[TENCHAT] Error posting photo: {e}")
            return {"status": "error", "error": str(e)}
    
    async def post_video(self, video_bytes: bytes, caption: str = "", title: str = "") -> dict:
        """Post video to Tenchat."""
        try:
            await self.page.goto("https://tenchat.ru/feed")
            await asyncio.sleep(2)
            
            # Click create post
            create_btn = await self.page.wait_for_selector(
                'button:has-text("Написать"), [data-testid="create-post"]',
                timeout=5000
            )
            await create_btn.click()
            await asyncio.sleep(1)
            
            # Fill title if provided
            if title:
                title_input = await self.page.query_selector('input[placeholder*="заголовок"], input[name="title"]')
                if title_input:
                    await title_input.fill(title)
                    await asyncio.sleep(0.5)
            
            # Fill caption
            if caption:
                text_input = await self.page.wait_for_selector(
                    'div[contenteditable="true"], textarea',
                    timeout=5000
                )
                await text_input.fill(caption)
                await asyncio.sleep(0.5)
            
            # Upload video
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
                f.write(video_bytes)
                tmp_path = f.name
            
            file_input = await self.page.wait_for_selector(
                'input[type="file"][accept*="video"]',
                timeout=5000
            )
            await file_input.set_input_files(tmp_path)
            await asyncio.sleep(2)
            
            os.unlink(tmp_path)
            
            # Wait for upload processing
            print("[TENCHAT] Waiting for video upload...")
            await asyncio.sleep(15)
            
            # Publish
            publish_btn = await self.page.wait_for_selector('button:has-text("Опубликовать")', timeout=5000)
            await publish_btn.click()
            await asyncio.sleep(3)
            
            return {"status": "ok", "platform": "tenchat", "type": "video"}
            
        except Exception as e:
            print(f"[TENCHAT] Error posting video: {e}")
            return {"status": "error", "error": str(e)}


# Convenience functions
async def post_text_tenchat(text: str, title: str = "") -> dict:
    """Post text to Tenchat."""
    agent = TenchatAgent(headless=True)
    try:
        await agent.start()
        if await agent.login():
            return await agent.post_text(text, title)
        return {"status": "error", "error": "Login failed"}
    finally:
        await agent.stop()


async def post_photo_tenchat(image_paths: List[Union[str, bytes]], caption: str = "", title: str = "") -> dict:
    """Post photo to Tenchat."""
    agent = TenchatAgent(headless=True)
    try:
        await agent.start()
        if await agent.login():
            return await agent.post_photo(image_paths, caption, title)
        return {"status": "error", "error": "Login failed"}
    finally:
        await agent.stop()


async def post_video_tenchat(video_bytes: bytes, caption: str = "", title: str = "") -> dict:
    """Post video to Tenchat."""
    agent = TenchatAgent(headless=True)
    try:
        await agent.start()
        if await agent.login():
            return await agent.post_video(video_bytes, caption, title)
        return {"status": "error", "error": "Login failed"}
    finally:
        await agent.stop()
