"""
Ручной первичный вход в TenChat.
Запускать один раз на сервере:
  python3 tenchat_login.py

После успешного входа сессия сохраняется в tenchat_session.json
и бот сможет работать автономно.
"""
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

PHONE        = __import__("os").getenv("TENCHAT_PHONE", "")
STATE_FILE   = Path(__file__).parent / "tenchat_session.json"


async def main():
    if not PHONE:
        print("❌ Задай TENCHAT_PHONE=79XXXXXXXXX в .env")
        return

    print(f"[TENCHAT] Запуск браузера для входа с номером +{PHONE}")
    print("[TENCHAT] ВНИМАНИЕ: нужен доступ к телефону для SMS-кода\n")

    async with async_playwright() as pw:
        # headless=False — открываем видимый браузер (если есть дисплей)
        # Если сервер без дисплея — используй xvfb-run:
        #   xvfb-run python3 tenchat_login.py
        browser = await pw.chromium.launch(
            headless=False,
            args=["--no-sandbox", "--disable-setuid-sandbox"],
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()

        print("[TENCHAT] Открываем страницу входа...")
        await page.goto("https://tenchat.ru/auth", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)

        # Ищем поле ввода телефона
        phone_sel = 'input[type="tel"], input[name="phone"], input[placeholder*="телефон"], input[placeholder*="номер"]'
        try:
            phone_input = await page.wait_for_selector(phone_sel, timeout=10000, state="visible")
            await phone_input.fill(f"+{PHONE}")
            print(f"[TENCHAT] Номер введён: +{PHONE}")
        except Exception as e:
            print(f"[TENCHAT] Не нашли поле телефона: {e}")
            print("[TENCHAT] Введи номер вручную в браузере")

        # Ждём кнопку «Продолжить» / «Получить код»
        submit_sel = 'button[type="submit"], button:has-text("Продолжить"), button:has-text("Получить код")'
        try:
            btn = await page.wait_for_selector(submit_sel, timeout=8000, state="visible")
            await btn.click()
            print("[TENCHAT] Отправлен запрос на SMS")
        except Exception:
            print("[TENCHAT] Нажми кнопку отправки SMS вручную")

        print("\n" + "=" * 50)
        print("ВВЕДИ КОД ИЗ SMS В БРАУЗЕРЕ")
        print("После входа нажми Enter здесь")
        print("=" * 50)
        input()

        # Проверяем — залогинены ли
        current_url = page.url
        print(f"[TENCHAT] Текущий URL: {current_url}")

        if "auth" in current_url or "login" in current_url:
            print("❌ Похоже, вход не выполнен. Попробуй ещё раз.")
        else:
            # Сохраняем сессию
            await context.storage_state(path=str(STATE_FILE))
            print(f"\n✅ Сессия сохранена → {STATE_FILE}")
            print("Теперь бот будет работать автономно.")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
