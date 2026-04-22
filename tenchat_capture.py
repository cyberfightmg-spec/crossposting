"""
Запуск на сервере (без дисплея):
  python3 tenchat_capture.py

Скрипт headless — браузер невидим, но работает полностью.
Номер телефона берётся из .env (TENCHAT_PHONE).
SMS-код вводишь в терминале.
"""
import asyncio
import json
import os
import sys
from pathlib import Path

BASE_DIR     = Path(__file__).parent
SESSION_FILE = BASE_DIR / "tenchat_session.json"
TOKEN_FILE   = BASE_DIR / "tenchat_token.json"
PHONE        = os.getenv("TENCHAT_PHONE", "")


async def main():
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("❌ Playwright не установлен.")
        print("   pip install playwright && playwright install chromium")
        sys.exit(1)

    if not PHONE:
        print("❌ Задай TENCHAT_PHONE=79XXXXXXXXX в .env")
        sys.exit(1)

    captured = {"token": None}

    print("=" * 50)
    print("  TenChat — захват сессии (server mode)")
    print("=" * 50)
    print(f"Телефон: +{PHONE}")
    print()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
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

        def on_request(request):
            auth = request.headers.get("authorization", "")
            if auth.startswith("Bearer ") and not captured["token"]:
                captured["token"] = auth.split(" ", 1)[1]
                print("✅ Bearer-токен перехвачен!")

        context.on("request", on_request)
        page = await context.new_page()

        # ── Шаг 1: открываем страницу входа ──────────────────────────────────
        print("Открываем tenchat.ru/auth ...")
        await page.goto("https://tenchat.ru/auth", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)
        print(f"URL: {page.url}")

        # ── Шаг 2: вводим телефон ─────────────────────────────────────────────
        phone_sel = (
            'input[type="tel"], '
            'input[name="phone"], '
            'input[placeholder*="Номер"], '
            'input[placeholder*="телефон"], '
            'input[placeholder*="номер"]'
        )
        try:
            inp = await page.wait_for_selector(phone_sel, timeout=10000, state="visible")
            await inp.click()
            await inp.fill(f"+{PHONE}")
            print(f"Телефон введён: +{PHONE}")
        except Exception:
            phone_val = PHONE
            print(f"Поле телефона не найдено автоматически.")
            print(f"Введи номер вручную если скрипт завис, или проверь страницу.")

        await page.wait_for_timeout(500)

        # ── Шаг 3: нажимаем «Продолжить» ─────────────────────────────────────
        submit_sel = (
            'button[type="submit"], '
            'button:has-text("Продолжить"), '
            'button:has-text("Получить код"), '
            'button:has-text("Войти")'
        )
        try:
            btn = await page.wait_for_selector(submit_sel, timeout=8000, state="visible")
            await btn.click()
            print("Запрос на SMS отправлен.")
        except Exception as e:
            print(f"Кнопка «Продолжить» не найдена: {e}")
            print("Возможно, форма выглядит иначе. Сохраняем скриншот для диагностики.")
            await page.screenshot(path=str(BASE_DIR / "tenchat_debug.png"))
            print(f"Скриншот: {BASE_DIR / 'tenchat_debug.png'}")

        await page.wait_for_timeout(2000)

        # ── Шаг 4: ждём SMS-код от пользователя ──────────────────────────────
        print()
        print("┌──────────────────────────────────────┐")
        print("│  Введи SMS-код из телефона:          │")
        print("└──────────────────────────────────────┘")
        sms_code = input("SMS-код: ").strip()

        # Вводим код
        code_sel = (
            'input[name="code"], '
            'input[type="text"][inputmode="numeric"], '
            'input[placeholder*="код"], '
            'input[placeholder*="Код"], '
            'input[autocomplete="one-time-code"]'
        )
        try:
            code_inp = await page.wait_for_selector(code_sel, timeout=10000, state="visible")
            await code_inp.fill(sms_code)
            await page.wait_for_timeout(500)

            # Пробуем нажать подтвердить
            confirm_sel = (
                'button[type="submit"], '
                'button:has-text("Подтвердить"), '
                'button:has-text("Войти"), '
                'button:has-text("Продолжить")'
            )
            try:
                confirm = await page.wait_for_selector(confirm_sel, timeout=5000, state="visible")
                await confirm.click()
            except Exception:
                # Некоторые формы принимают код без кнопки (автосабмит)
                await code_inp.press("Enter")

        except Exception as e:
            print(f"Поле кода не найдено: {e}")
            print("Возможно, код принят автоматически или форма изменилась.")

        # ── Шаг 5: ждём редирект на ленту ────────────────────────────────────
        print("Ожидаем вход...")
        await page.wait_for_timeout(5000)

        # Если не на ленте — пробуем перейти сами
        if "feed" not in page.url and "auth" in page.url:
            await page.goto("https://tenchat.ru/feed", wait_until="domcontentloaded", timeout=15000)
            await page.wait_for_timeout(3000)

        print(f"URL после входа: {page.url}")

        if "auth" in page.url or "login" in page.url:
            print("❌ Вход не удался — всё ещё на странице авторизации.")
            await page.screenshot(path=str(BASE_DIR / "tenchat_debug.png"))
            print(f"   Скриншот сохранён: tenchat_debug.png")
            await browser.close()
            return

        # ── Шаг 6: даём время перехватить токен из API-запросов ──────────────
        print("Перехватываем токен из API-запросов...")
        await page.wait_for_timeout(4000)

        # Если токен ещё не перехвачен — пробуем из localStorage
        if not captured["token"]:
            try:
                token_ls = await page.evaluate("""
                    () => {
                        const keys = Object.keys(localStorage);
                        for (const key of keys) {
                            const val = localStorage.getItem(key);
                            try {
                                const obj = JSON.parse(val);
                                if (obj && typeof obj === 'object') {
                                    const t = obj.token || obj.access_token || obj.accessToken || obj.jwt;
                                    if (t && t.length > 50) return t;
                                }
                            } catch(e) {}
                        }
                        return null;
                    }
                """)
                if token_ls:
                    captured["token"] = token_ls
                    print("✅ Токен найден в localStorage!")
            except Exception as e:
                print(f"localStorage: {e}")

        # ── Шаг 7: сохраняем результаты ──────────────────────────────────────
        await context.storage_state(path=str(SESSION_FILE))
        print(f"\n✅ Сессия сохранена  → {SESSION_FILE}")

        if captured["token"]:
            TOKEN_FILE.write_text(
                json.dumps({"token": captured["token"]}, ensure_ascii=False, indent=2)
            )
            print(f"✅ Токен сохранён    → {TOKEN_FILE}")
        else:
            print("⚠️  Токен не перехвачен — бот будет работать через cookies сессии.")

        await browser.close()

    print()
    print("=" * 50)
    print("  Готово! Данные сохранены на сервере.")
    print("  Бот TenChat готов к работе.")
    print("=" * 50)


if __name__ == "__main__":
    # Загружаем .env если есть
    try:
        from dotenv import load_dotenv
        load_dotenv()
        PHONE = os.getenv("TENCHAT_PHONE", PHONE)
    except ImportError:
        pass

    asyncio.run(main())
