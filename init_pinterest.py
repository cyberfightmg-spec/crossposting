"""
Скрипт первичной авторизации Pinterest.
Запускать один раз: python init_pinterest.py
Сохраняет куки в /root/crossposting/pinterest_creds/cookies.json (действуют ~15 дней).
"""
import asyncio
from playwright.async_api import async_playwright
from tools.pinterest import _login, CRED_ROOT

async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
        context = await browser.new_context(viewport={"width": 1280, "height": 900})
        page = await context.new_page()
        ok = await _login(page, context)
        await browser.close()
    if ok:
        print(f"✅ Pinterest авторизован, куки сохранены в {CRED_ROOT}/cookies.json")
    else:
        print("❌ Авторизация не удалась — проверьте PINTEREST_EMAIL и PINTEREST_PASSWORD в .env")

if __name__ == "__main__":
    asyncio.run(main())
