"""
Запусти локально на своём компьютере (не на сервере):
  pip install playwright
  playwright install chromium
  python3 tenchat_capture.py

Откроется браузер — войди в TenChat, затем нажми Enter в терминале.
Скрипт сохранит tenchat_session.json и tenchat_token.json.
"""
import asyncio
import json
import sys
from pathlib import Path

SESSION_FILE = Path("tenchat_session.json")
TOKEN_FILE   = Path("tenchat_token.json")


async def main():
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("❌ Playwright не установлен.")
        print("   pip install playwright && playwright install chromium")
        sys.exit(1)

    captured = {"token": None, "cookies": []}

    print("=" * 55)
    print("  TenChat — захват сессии")
    print("=" * 55)
    print()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=False,
            args=[
                "--no-sandbox",
                "--start-maximized",
                "--disable-blink-features=AutomationControlled",
            ],
            slow_mo=50,
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

        # Перехватываем Bearer-токен из любого запроса
        def on_request(request):
            auth = request.headers.get("authorization", "")
            if auth.startswith("Bearer ") and not captured["token"]:
                captured["token"] = auth.split(" ", 1)[1]
                print(f"\n✅ Bearer-токен перехвачен автоматически!")

        context.on("request", on_request)

        page = await context.new_page()

        print("Открываем TenChat...")
        await page.goto("https://tenchat.ru/auth", wait_until="domcontentloaded", timeout=30000)

        print()
        print("┌─────────────────────────────────────────────┐")
        print("│  Браузер открыт.                            │")
        print("│                                             │")
        print("│  1. Введи номер телефона                    │")
        print("│  2. Введи SMS-код                           │")
        print("│  3. Убедись что лента загрузилась           │")
        print("│                                             │")
        print("│  Затем вернись сюда и нажми Enter ↵        │")
        print("└─────────────────────────────────────────────┘")
        input()

        # Если токен ещё не захвачен — пробуем триггернуть запрос к API
        if not captured["token"]:
            print("\nПробуем перехватить токен через ленту...")
            try:
                await page.goto("https://tenchat.ru/feed", wait_until="domcontentloaded", timeout=15000)
                await page.wait_for_timeout(3000)
            except Exception:
                pass

        # Сохраняем storage_state (cookies + localStorage)
        await context.storage_state(path=str(SESSION_FILE))
        print(f"\n✅ Сессия сохранена    → {SESSION_FILE}")

        # Сохраняем токен
        token_data = {}
        if captured["token"]:
            token_data["token"] = captured["token"]
            TOKEN_FILE.write_text(json.dumps(token_data, ensure_ascii=False, indent=2))
            print(f"✅ Токен сохранён      → {TOKEN_FILE}")
        else:
            # Пробуем достать из localStorage
            try:
                token_ls = await page.evaluate("""
                    () => {
                        for (let key of Object.keys(localStorage)) {
                            let val = localStorage.getItem(key);
                            try {
                                let parsed = JSON.parse(val);
                                if (parsed && (parsed.token || parsed.access_token || parsed.accessToken)) {
                                    return parsed.token || parsed.access_token || parsed.accessToken;
                                }
                            } catch(e) {}
                            if (val && val.length > 100 && val.length < 500 && !val.includes(' ')) {
                                return val;
                            }
                        }
                        return null;
                    }
                """)
                if token_ls:
                    token_data["token"] = token_ls
                    TOKEN_FILE.write_text(json.dumps(token_data, ensure_ascii=False, indent=2))
                    print(f"✅ Токен из localStorage → {TOKEN_FILE}")
                else:
                    print("⚠️  Токен не найден — бот будет использовать cookies из session.json")
            except Exception as e:
                print(f"⚠️  Не удалось извлечь токен: {e}")

        await browser.close()

    print()
    print("=" * 55)
    print("  Готово! Теперь залей файлы на сервер:")
    print()
    print("  git add -f tenchat_session.json tenchat_token.json")
    print("  git commit -m 'Add TenChat session'")
    print("  git push")
    print()
    print("  На сервере:")
    print("  git pull")
    print()
    print("  ⚠️  После переноса удали файлы из git:")
    print("  git rm --cached tenchat_session.json tenchat_token.json")
    print("  git commit -m 'Remove session from git'")
    print("=" * 55)


if __name__ == "__main__":
    asyncio.run(main())
