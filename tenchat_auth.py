#!/usr/bin/env python3
"""
Скрипт для первичной авторизации в Tenchat.
Запускать один раз для сохранения сессии.
"""
import asyncio
import sys
import threading
sys.path.insert(0, '/root/crossposting')

from tools.tenchat import TenchatAgent, TENCHAT_PHONE, TENCHAT_STATE_FILE

sms_code = None
code_received = threading.Event()

def wait_for_sms():
    """Ожидаем ввод кода от пользователя."""
    global sms_code
    print("\n" + "="*60)
    print("📱 ВВЕДИТЕ КОД ИЗ SMS!")
    print("="*60)
    print(f"Код придёт на номер: +{TENCHAT_PHONE}")
    print("Введите код здесь и нажмите Enter:")
    print("="*60)
    sms_code = input("> ").strip()
    code_received.set()

async def main():
    print("="*60)
    print("TENCHAT AUTH - Первичная авторизация")
    print("="*60)
    print(f"\nТелефон: +{TENCHAT_PHONE}")
    print("\nЗапускаю браузер...")
    print("="*60 + "\n")
    
    agent = TenchatAgent(headless=True)
    
    try:
        await agent.start()
        
        # Проверяем есть ли уже сессия
        if await agent.is_logged_in():
            print("✅ Уже авторизованы!")
            await agent._save_session()
            return
        
        # Идём на страницу логина
        await agent.page.goto("https://tenchat.ru/auth/sign-in", timeout=60000)
        await asyncio.sleep(5)
        
        print(f"URL: {agent.page.url}")
        
        # Ищем поле телефона
        phone_input = await agent.page.wait_for_selector('input[type="tel"]', timeout=10000)
        print("✅ Найдено поле ввода телефона")
        
        # Вводим телефон
        phone_formatted = f"+{TENCHAT_PHONE}"
        await phone_input.fill(phone_formatted)
        print(f"✅ Телефон введён: {phone_formatted}")
        
        # Ищем и нажимаем кнопку
        submit_btn = await agent.page.wait_for_selector('button:has-text("Продолжить")', timeout=5000)
        await submit_btn.click()
        print("✅ Отправлен запрос кода...")
        
        # Ждём появления поля для кода
        await asyncio.sleep(3)
        
        # Запускаем поток для ожидания ввода кода
        input_thread = threading.Thread(target=wait_for_sms)
        input_thread.daemon = True
        input_thread.start()
        
        # Ждём код (до 5 минут)
        print("\n⏳ Ожидаю код из SMS (5 минут)...")
        code_received.wait(timeout=300)
        
        if not sms_code:
            print("❌ Код не введён вовремя")
            return
        
        print(f"\n✅ Получен код: {sms_code}")
        print("Ввожу код в браузер...")
        
        # Ищем поле для кода (обычно input type="text" или с placeholder содержащим "код")
        code_input = None
        for selector in ['input[type="text"]', 'input[inputmode="numeric"]', 'input[placeholder*="код" i]', 'input[placeholder*="Код" i]']:
            try:
                code_input = await agent.page.wait_for_selector(selector, timeout=3000)
                if code_input:
                    print(f"✅ Найдено поле для кода: {selector}")
                    break
            except:
                continue
        
        if not code_input:
            print("⚠️ Поле для кода не найдено автоматически")
            print("Пробую найти все input поля...")
            inputs = await agent.page.query_selector_all('input')
            for inp in inputs:
                input_type = await inp.get_attribute('type')
                if input_type in ['text', 'tel', 'number']:
                    code_input = inp
                    print(f"✅ Выбрано поле type={input_type}")
                    break
        
        if not code_input:
            print("❌ Не удалось найти поле для кода")
            return
        
        # Вводим код
        await code_input.fill(sms_code)
        print("✅ Код введён в поле")
        
        # Ищем кнопку подтверждения (обычно "Войти" или "Подтвердить")
        confirm_btn = None
        for btn_text in ["Войти", "Подтвердить", "Продолжить"]:
            try:
                confirm_btn = await agent.page.wait_for_selector(f'button:has-text("{btn_text}")', timeout=2000)
                if confirm_btn:
                    print(f"✅ Найдена кнопка: {btn_text}")
                    break
            except:
                continue
        
        if not confirm_btn:
            # Берём первую кнопку submit
            confirm_btn = await agent.page.wait_for_selector('button[type="submit"], button', timeout=5000)
        
        await confirm_btn.click()
        print("✅ Отправляю код...")
        
        # Ждём обработки
        await asyncio.sleep(5)
        
        # Проверяем успешность
        if await agent.is_logged_in():
            await agent._save_session()
            print("\n" + "="*60)
            print("🎉 АВТОРИЗАЦИЯ УСПЕШНА!")
            print("="*60)
            print(f"✅ Сессия сохранена: {TENCHAT_STATE_FILE}")
            print("✅ Теперь можно запускать бота в обычном режиме.")
            print("="*60)
        else:
            print("\n" + "="*60)
            print("❌ Авторизация не удалась")
            print(f"URL: {agent.page.url}")
            # Делаем скриншот для диагностики
            await agent.page.screenshot(path="/root/crossposting/tenchat_error.png")
            print("📸 Скриншот сохранён: tenchat_error.png")
            print("="*60)
            
    except Exception as e:
        print(f"\n❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await agent.stop()

if __name__ == "__main__":
    asyncio.run(main())
