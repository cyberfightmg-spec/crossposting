#!/usr/bin/env python3
"""Простой OAuth callback сервер для Pinterest."""

import os
import base64
import json
import asyncio
import httpx
import hashlib
import secrets
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
from dotenv import load_dotenv

load_dotenv()

APP_ID = os.getenv("PINTEREST_APP_ID")
APP_SECRET = os.getenv("PINTEREST_APP_SECRET")
TOKEN_FILE = "/root/pinterest_token.json"

code_verifier = secrets.token_urlsafe(64)
code_challenge = base64.urlsafe_b64encode(
    hashlib.sha256(code_verifier.encode()).digest()
).rstrip(b'=').decode()

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        global _code
        params = parse_qs(urlparse(self.path).query)
        if "code" in params:
            _code = params["code"][0]
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK - Code received!")
        else:
            self.send_response(400)
            self.end_headers()
    def log_message(self, *args): pass

_code = None

async def exchange(code: str, redirect_uri: str):
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
                "redirect_uri": redirect_uri,
                "code_verifier": code_verifier,
            },
            timeout=20,
        )
        return r.json()

print("=" * 60)
print("Pinterest OAuth Callback Server")
print("=" * 60)
print()
print(f"code_verifier: {code_verifier}")
print()
print("Auth URL:")
redirect_uri = "https://57af0192b8f2dde2-103-181-182-213.serveousercontent.com/callback"
scope = "boards:read boards:write pins:read pins:write user_accounts:read"
auth_url = f"https://www.pinterest.com/oauth/?client_id={APP_ID}&redirect_uri={redirect_uri}&response_type=code&scope={scope}&code_challenge={code_challenge}&code_challenge_method=S256"
print(auth_url)
print()
print("Откройте ссылку в браузере и авторизуйтесь.")
print()

server = HTTPServer(("0.0.0.0", 8089), Handler)
import threading
t = threading.Thread(target=server.serve_forever)
t.daemon = True
t.start()

print("Ожидание callback...")
import time
start = time.time()
while _code is None and time.time() - start < 120:
    time.sleep(0.5)

if not _code:
    print("Таймаут!")
    exit(1)

print(f"Код получен!")

result = asyncio.run(exchange(_code, redirect_uri))

if "access_token" not in result:
    print(f"Ошибка: {result}")
    exit(1)

result["obtained_at"] = int(time.time())
with open(TOKEN_FILE, "w") as f:
    json.dump(result, f, indent=2)

print(f"Токен сохранён в {TOKEN_FILE}")
print(f"expires_in: {result.get('expires_in', 0) // 86400} дней")
