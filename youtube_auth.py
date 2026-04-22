#!/usr/bin/env python3
"""Скрипт для получения refresh_token YouTube."""

import os
import json
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials

CLIENT_SECRET_FILE = "youtube_client_secret.json"
TOKEN_FILE = "youtube_token.json"

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube"
]


def get_auth_url():
    """Генерирует ссылку для авторизации."""
    if not os.path.exists(CLIENT_SECRET_FILE):
        print(f"❌ Файл {CLIENT_SECRET_FILE} не найден!")
        print("Создайте его в формате:")
        print(json.dumps({
            "installed": {
                "client_id": "YOUR_CLIENT_ID",
                "client_secret": "YOUR_CLIENT_SECRET",
                "redirect_uris": ["http://localhost"]
            }
        }, indent=2))
        return None, None
    
    flow = InstalledAppFlow.from_client_secrets_file(
        CLIENT_SECRET_FILE, SCOPES
    )
    
    auth_url, state = flow.authorization_url(prompt="consent")
    return auth_url, state


def main():
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "--url":
        start_web_server()
        return
    
    if len(sys.argv) > 2 and sys.argv[1] == "--code":
        code = sys.argv[2]
        exchange_code(code)
        return
    
    print("Usage:")
    print("  python youtube_auth.py --url    # Запустить веб-сервер с ссылкой")
    print("  python youtube_auth.py --code <CODE>  # Обменять код на токен")


def start_web_server():
    from http.server import HTTPServer, BaseHTTPRequestHandler
    import urllib.parse
    
    auth_url, state = get_auth_url()
    if not auth_url:
        return
    
    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><title>YouTube Auth</title></head>
<body style="font-family:sans-serif;padding:40px;text-align:center">
<h2>Авторизация YouTube</h2>
<p><a href="{auth_url}" style="font-size:20px;color:#065fd4">👉 Нажмите здесь для авторизации</a></p>
<p>После авторизации вы будете перенаправлены на страницу с кодом.</p>
<p>Скопируйте код из URL (параметр <code>code</code>) и введите его ниже:</p>
<form method="get" action="/">
<input type="text" name="code" placeholder="ВАШ_КОД" style="padding:10px;width:300px">
<button type="submit" style="padding:10px 20px;cursor:pointer">Отправить</button>
</form>
</body>
</html>"""
    
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if "code=" in self.path:
                parsed = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                code = parsed.get("code", [""])[0]
                self.send_response(200)
                self.end_headers()
                if code:
                    self.wfile.write("<html><body style='font-family:sans-serif;padding:40px;text-align:center'><h2>Code received!</h2><p>Script will exchange it for token...</p></body></html>".encode())
                    print(f"\n🔑 Получен код: {code[:30]}...")
                    exchange_code(code)
                    print("✅ Готово! Токен сохранён.")
                    return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html.encode())
        
        def log_message(self, format, *args):
            pass
    
    print(f"\n🚀 Сервер запущен: http://localhost:8080")
    print("Нажмите Ctrl+C для остановки\n")
    
    server = HTTPServer(("0.0.0.0", 8080), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 Сервер остановлен")
        server.server_close()


def exchange_code(code: str):
    """Обменивает код на токены."""
    if not os.path.exists(CLIENT_SECRET_FILE):
        print(f"❌ Файл {CLIENT_SECRET_FILE} не найден!")
        return
    
    flow = InstalledAppFlow.from_client_secrets_file(
        CLIENT_SECRET_FILE, SCOPES
    )
    
    flow.fetch_token(code=code)
    creds = flow.credentials
    
    token_data = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes)
    }
    
    with open(TOKEN_FILE, "w") as f:
        json.dump(token_data, f, indent=2)
    
    print(f"✅ Токен сохранён в {TOKEN_FILE}")
    if creds.refresh_token:
        print(f"refresh_token: {creds.refresh_token[:30]}...")
    else:
        print("⚠️ refresh_token не получен. Попробуйте с --url ещё раз.")


if __name__ == "__main__":
    main()