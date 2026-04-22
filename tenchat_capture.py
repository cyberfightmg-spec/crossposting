"""
ЗАПУСКАЙ НА СВОЁМ КОМПЬЮТЕРЕ (не на сервере):

  pip install playwright
  playwright install chromium
  python3 tenchat_capture.py

Откроется браузер, войди в TenChat, нажми Enter.
Файлы tenchat_session.json и tenchat_token.json сохранятся рядом.
Потом залей их на сервер через scp или git.
"""
import asyncio
import json
import os
import sys
from pathlib import Path

SESSION_FILE = Path("tenchat_session.json")
TOKEN_FILE   = Path("tenchat_token.json")
PHONE        = os.getenv("TENCHAT_PHONE", "")


async def main():
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("❌  Установи playwright:")
        print("    pip install playwright")
        print("    playwright install chromium")
        sys.exit(1)

    captured = {"token": None}

    print("=" * 52)
    print("  TenChat — захват сессии")
    print("=" * 52)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=False,          # видимый браузер
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--start-maximized",
            ],
        )
        context = await browser.new_context(
            viewport={"width": 1440, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="ru-RU",
        )

        # Перехватываем Bearer-токен из любого запроса браузера
        def on_request(request):
            auth = request.headers.get("authorization", "")
            if auth.startswith("Bearer ") and not captured["token"]:
                captured["token"] = auth.split(" ", 1)[1]
                print("\n✅  Bearer-токен перехвачен автоматически!")

        context.on("request", on_request)
        page = await context.new_page()

        print("\nОткрываем tenchat.ru ...")
        await page.goto("https://tenchat.ru/auth", wait_until="domcontentloaded", timeout=60000)

        # Если номер задан — пробуем вставить автоматически
        if PHONE:
            try:
                inp = await page.wait_for_selector(
                    'input[type="tel"], input[name="phone"]',
                    timeout=5000, state="visible"
                )
                await inp.fill(f"+{PHONE}")
                print(f"Номер вставлен: +{PHONE}")
            except Exception:
                pass

        print()
        print("┌─────────────────────────────────────────┐")
        print("│  Браузер открыт.                        │")
        print("│                                         │")
        print("│  1. Введи номер телефона (если пусто)   │")
        print("│  2. Получи SMS и введи код              │")
        print("│  3. Дождись загрузки ленты              │")
        print("│                                         │")
        print("│  Затем вернись сюда → нажми Enter ↵    │")
        print("└─────────────────────────────────────────┘")
        input()

        # Триггерим API-запросы чтобы перехватить токен
        if not captured["token"]:
            try:
                await page.goto("https://tenchat.ru/feed", wait_until="domcontentloaded", timeout=20000)
                await page.wait_for_timeout(3000)
            except Exception:
                pass

        # Пробуем достать токен из localStorage
        if not captured["token"]:
            try:
                t = await page.evaluate("""() => {
                    for (const key of Object.keys(localStorage)) {
                        const raw = localStorage.getItem(key);
                        try {
                            const obj = JSON.parse(raw);
                            if (obj && typeof obj === 'object') {
                                const t = obj.token || obj.access_token ||
                                          obj.accessToken || obj.jwt;
                                if (t && t.length > 50) return t;
                            }
                        } catch(e) {}
                    }
                    return null;
                }""")
                if t:
                    captured["token"] = t
                    print("✅  Токен найден в localStorage!")
            except Exception:
                pass

        # Сохраняем
        await context.storage_state(path=str(SESSION_FILE))
        print(f"\n✅  Сессия сохранена  → {SESSION_FILE}")

        if captured["token"]:
            TOKEN_FILE.write_text(
                json.dumps({"token": captured["token"]}, indent=2, ensure_ascii=False)
            )
            print(f"✅  Токен сохранён   → {TOKEN_FILE}")
        else:
            print("⚠️   Токен не найден — бот будет работать только через cookies.")

        await browser.close()

    print()
    print("=" * 52)
    print("  Готово! Теперь скопируй файлы на сервер:")
    print()
    print("  Вариант 1 — scp (рекомендуется):")
    print("  scp tenchat_session.json tenchat_token.json \\")
    print("      root@<IP_СЕРВЕРА>:/root/crossposting/")
    print()
    print("  Вариант 2 — через git:")
    print("  git add -f tenchat_session.json tenchat_token.json")
    print("  git commit -m 'tenchat session'")
    print("  git push")
    print("  # на сервере: git pull")
    print("  # после переноса: git rm --cached tenchat_*.json && git commit")
    print("=" * 52)


if __name__ == "__main__":
    try:
        from dotenv import load_dotenv
        load_dotenv()
        PHONE = os.getenv("TENCHAT_PHONE", PHONE)
    except ImportError:
        pass

    asyncio.run(main())
