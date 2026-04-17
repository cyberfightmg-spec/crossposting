"""
Одноразовый скрипт для получения Pinterest OAuth-токенов.

Запуск:
    python get_pinterest_token.py

Что нужно заранее:
  1. В .env прописать:
       PINTEREST_APP_ID=1562168
       PINTEREST_APP_SECRET=твой_секрет
  2. В настройках приложения на developers.pinterest.com → Redirect links добавить:
       https://localhost/callback

После запуска:
  - Скрипт покажет ссылку для авторизации
  - После подтверждения браузер перенаправит на https://localhost/callback?code=...
    (страница не откроется — это нормально)
  - Скопируйте полный URL из адресной строки и вставьте в терминал
  - Токены сохранятся в /root/pinterest_token.json
"""

import os
import json
import base64
import asyncio
import webbrowser
from urllib.parse import urlparse, parse_qs
import httpx
from dotenv import load_dotenv

load_dotenv()

APP_ID = os.getenv("PINTEREST_APP_ID")
APP_SECRET = os.getenv("PINTEREST_APP_SECRET")
REDIRECT_URI = "https://sad-trams-push.loca.lt/callback"
TOKEN_FILE = "/root/pinterest_token.json"
SCOPES = "boards:read,boards:write,pins:read,pins:write,user_accounts:read"


async def exchange_code(code: str) -> dict:
    credentials = base64.b64encode(f"{APP_ID}:{APP_SECRET}".encode()).decode()
    async with httpx.AsyncClient() as client:
        r = await client.post(
            "https://api.pinterest.com/v5/oauth/token",
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
            },
            timeout=20,
        )
        return r.json()


async def main():
    if not APP_ID or not APP_SECRET:
        print("❌ Не заданы PINTEREST_APP_ID и/или PINTEREST_APP_SECRET в .env")
        return

    auth_url = (
        f"https://www.pinterest.com/oauth/"
        f"?client_id={APP_ID}"
        f"&redirect_uri={REDIRECT_URI}"
        f"&response_type=code"
        f"&scope={SCOPES}"
    )

    print("\n" + "=" * 60)
    print("Pinterest OAuth — получение токенов")
    print("=" * 60)

    print("\nШаг 1. Убедитесь, что в настройках приложения на")
    print("       developers.pinterest.com → Redirect links добавлено:")
    print(f"       {REDIRECT_URI}")

    print("\nШаг 2. Откройте эту ссылку в браузере:\n")
    print(f"  {auth_url}")

    try:
        webbrowser.open(auth_url)
    except Exception:
        pass

    print("\nШаг 3. Подтвердите доступ.")
    print("       Браузер попытается открыть https://localhost/callback?code=...")
    print("       Страница не загрузится — это нормально.")
    print("       Скопируйте ПОЛНЫЙ URL из адресной строки браузера.\n")

    redirect_url = input("Вставьте URL сюда: ").strip()

    params = parse_qs(urlparse(redirect_url).query)
    code = params.get("code", [None])[0]

    if not code:
        print(f"❌ Не удалось найти code в URL: {redirect_url}")
        print("   Убедитесь, что скопировали полный URL с параметром ?code=...")
        return

    print(f"\n✅ Код получен, обмениваю на токен...")
    tokens = await exchange_code(code)

    if "access_token" not in tokens:
        print(f"❌ Не удалось получить токен: {tokens}")
        return

    import time
    tokens["obtained_at"] = int(time.time())

    with open(TOKEN_FILE, "w") as f:
        json.dump(tokens, f, indent=2)

    expires_days = tokens.get("expires_in", 0) // 86400
    refresh_days = tokens.get("refresh_token_expires_in", 0) // 86400

    print(f"\n✅ Токены сохранены в {TOKEN_FILE}")
    print(f"   access_token  : действует {expires_days} дней")
    print(f"   refresh_token : действует {refresh_days} дней")
    print("\nБот будет использовать API и автоматически обновлять токен.\n")


if __name__ == "__main__":
    asyncio.run(main())
