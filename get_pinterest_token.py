"""
Одноразовый скрипт для получения Pinterest OAuth-токенов.

Запуск:
    python get_pinterest_token.py

Что нужно заранее:
  1. В .env прописать:
       PINTEREST_APP_ID=1562168
       PINTEREST_APP_SECRET=твой_секрет
  2. В настройках приложения на developers.pinterest.com добавить
     Redirect URI: http://localhost:8088/callback

После запуска:
  - Скрипт откроет ссылку для авторизации
  - После подтверждения токены сохранятся в /root/pinterest_token.json
  - access_token действует 30 дней, refresh_token — 1 год
  - pinterest.py автоматически обновляет токен через refresh_token
"""

import os
import json
import base64
import asyncio
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import httpx
from dotenv import load_dotenv

load_dotenv()

APP_ID = os.getenv("PINTEREST_APP_ID")
APP_SECRET = os.getenv("PINTEREST_APP_SECRET")
REDIRECT_URI = "http://localhost:8088/callback"
TOKEN_FILE = "/root/pinterest_token.json"
SCOPES = "boards:read,boards:write,pins:read,pins:write,user_accounts:read"

_auth_code = None


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global _auth_code
        params = parse_qs(urlparse(self.path).query)
        if "code" in params:
            _auth_code = params["code"][0]
            self.send_response(200)
            self.end_headers()
            self.wfile.write("✅ Авторизация прошла успешно! Вкладку можно закрыть.".encode())
        else:
            self.send_response(400)
            self.end_headers()
            error = params.get("error", ["unknown"])[0]
            self.wfile.write(f"❌ Ошибка: {error}".encode())

    def log_message(self, *args):
        pass


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
    print("       developers.pinterest.com добавлен Redirect URI:")
    print(f"       {REDIRECT_URI}")
    print("\nШаг 2. Откройте эту ссылку в браузере:\n")
    print(f"  {auth_url}\n")

    try:
        webbrowser.open(auth_url)
        print("(Браузер открыт автоматически)")
    except Exception:
        pass

    print("\nОжидаю подтверждения (до 2 минут)...\n")

    server = HTTPServer(("localhost", 8088), _CallbackHandler)
    server.timeout = 10

    for _ in range(12):  # 12 × 10s = 120s
        server.handle_request()
        if _auth_code:
            break

    if not _auth_code:
        print("❌ Время ожидания истекло. Попробуйте снова.")
        return

    print("✅ Код получен, обмениваю на токен...")
    tokens = await exchange_code(_auth_code)

    if "access_token" not in tokens:
        print(f"❌ Не удалось получить токен: {tokens}")
        return

    import time
    tokens["obtained_at"] = int(time.time())

    os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
    with open(TOKEN_FILE, "w") as f:
        json.dump(tokens, f, indent=2)

    expires_days = tokens.get("expires_in", 0) // 86400
    refresh_days = tokens.get("refresh_token_expires_in", 0) // 86400

    print(f"\n✅ Токены сохранены в {TOKEN_FILE}")
    print(f"   access_token  : действует {expires_days} дней")
    print(f"   refresh_token : действует {refresh_days} дней")
    print("\nТеперь можно запускать бота — pinterest.py будет")
    print("использовать API и автоматически обновлять токен.\n")


if __name__ == "__main__":
    asyncio.run(main())
