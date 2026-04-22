"""
Проверяет, работает ли сохранённый TenChat токен.
  python3 tenchat_check.py
"""
import asyncio
import json
import httpx
from pathlib import Path

TOKEN_FILE = Path(__file__).parent / "tenchat_token.json"

HEADERS = {
    "Accept": "application/json",
    "Origin": "https://tenchat.ru",
    "Referer": "https://tenchat.ru/feed",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}

PROFILE_ENDPOINTS = [
    "https://tenchat.ru/api/v1/user/me",
    "https://tenchat.ru/api/v2/user/me",
    "https://tenchat.ru/api/user/profile",
    "https://tenchat.ru/api/v1/profile",
    "https://tenchat.ru/api/me",
]


async def check():
    if not TOKEN_FILE.exists():
        print("❌  tenchat_token.json не найден")
        print("   Запусти: python3 tenchat_set_token.py <ТОКЕН>")
        return

    data = json.loads(TOKEN_FILE.read_text())
    token = data.get("token", "")
    if not token:
        print("❌  Токен пустой в tenchat_token.json")
        return

    print(f"Токен: {token[:20]}...{token[-10:]} (длина {len(token)})")
    print()

    headers = {**HEADERS, "Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        for url in PROFILE_ENDPOINTS:
            try:
                r = await client.get(url, headers=headers)
                print(f"  {url}")
                print(f"  → {r.status_code}")
                if r.status_code == 200:
                    body = r.json() if "application/json" in r.headers.get("content-type", "") else {}
                    name = (
                        body.get("name") or body.get("full_name") or
                        body.get("firstName") or body.get("username") or "?"
                    )
                    print(f"  ✅  Токен рабочий! Пользователь: {name}")
                    return
                elif r.status_code in (401, 403):
                    print(f"  ❌  Токен устарел или недействителен")
                else:
                    print(f"  ⚠️  {r.text[:100]}")
            except Exception as e:
                print(f"  ⚠️  {e}")
            print()

    print("Эндпоинты профиля не найдены — токен нужно проверить вручную")
    print("Попробуй запустить tenchat_capture.py (нужен локальный компьютер)")


asyncio.run(check())
