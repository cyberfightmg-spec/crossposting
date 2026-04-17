import asyncio
import os
from playwright.async_api import async_playwright
from dotenv import load_dotenv

load_dotenv()

APP_ID = os.getenv("PINTEREST_APP_ID")

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()
        
        url = (
            f"https://www.pinterest.com/oauth/"
            f"?client_id={APP_ID}"
            f"&redirect_uri=https://bore.pub:59610/callback"
            f"&response_type=code"
            f"&scope=boards:read,boards:write,pins:read,pins:write,user_accounts:read"
            f"&code_challenge=lR1gY7QgmcI052D-JgXBlyEVNXJS0gERPOZkBAdLkg0"
            f"&code_challenge_method=S256"
        )
        
        print(f"Открываю: {url}")
        await page.goto(url)
        print("Жду авторизацию...")
        print("После авторизации скажите 'готов'")
        
        input()
        
        current_url = page.url
        print(f"Текущий URL: {current_url}")
        
        await browser.close()

asyncio.run(main())
