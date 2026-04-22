#!/usr/bin/env python3
"""
Скрипт для авторизации в Tenchat.
Запусти на своём компьютере, войди в Tenchat, и скрипт сохранит сессию.
"""

import asyncio
from playwright.async_api import async_playwright

TENCHAT_PHONE = "79169547408"

async def main():
    print("="*60)
    print("TENCHAT АВТОРИЗАЦИЯ")
    print("="*60)
    print(f"\nТелефон: +{TENCHAT_PHONE}")
    print("\nОткроется браузер. Войди в Tenchat.")
    print("="*60 + "\n")
    
    async with async_playwright() as p:
        # Запускаем видимый браузер
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800}
        )
        page = await context.new_page()
        
        # Открываем страницу входа
        print("1. Открываю tenchat.ru/auth/sign-in...")
        await page.goto("https://tenchat.ru/auth/sign-in")
        await asyncio.sleep(2)
        
        # Вводим телефон
        print(f"2. Ввожу телефон: +{TENCHAT_PHONE}")
        await page.fill('input[type="tel"]', f"+{TENCHAT_PHONE}")
        
        # Нажимаем продолжить
        await page.click('button:has-text("Продолжить")')
        print("3. ✅ Код отправлен на SMS!")
        print()
        print("="*60)
        print("📱 ВВЕДИ КОД ИЗ SMS В БРАУЗЕРЕ")
        print("и нажми 'Войти'")
        print("="*60)
        print()
        
        # Ждём пока пользователь войдёт
        print("Жду входа... (120 секунд максимум)")
        logged_in = False
        for i in range(120):
            await asyncio.sleep(1)
            current_url = page.url
            if "/auth" not in current_url and "/login" not in current_url:
                logged_in = True
                break
            if i % 10 == 0:
                print(f"  Ожидание... ({i} сек)")
        
        if logged_in:
            print("\n✅ Вход выполнен!")
            
            # Сохраняем сессию
            await context.storage_state(path="tenchat_session.json")
            print("✅ Сессия сохранена в файл: tenchat_session.json")
            print()
            print("="*60)
            print("ДЕЙСТВИЯ:")
            print("1. Отправь файл tenchat_session.json мне")
            print("2. Я скопирую его на сервер")
            print("3. Готово! Tenchat будет работать автоматически")
            print("="*60)
        else:
            print("\n⚠️ Время ожидания истекло")
            print("Возможно ты не успел войти")
        
        input("\nНажми Enter чтобы закрыть браузер...")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
