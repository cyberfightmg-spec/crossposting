"""
Сохрани Bearer-токен TenChat вручную.

Способ 1 — аргумент:
  python3 tenchat_set_token.py eyJhbGciOiJSUzI1NiJ9...

Способ 2 — переменная окружения:
  TENCHAT_TOKEN=eyJ... python3 tenchat_set_token.py

Как получить токен через HTTP Toolkit (Android):
  1. Установи HTTP Toolkit из Google Play
  2. Запусти, открой TenChat в приложении
  3. Найди любой запрос на tenchat.ru
  4. Скопируй заголовок: Authorization: Bearer <ТОКЕН>
  5. Запусти этот скрипт с токеном

После сохранения бот будет постить через прямое API без браузера.
"""
import json
import os
import sys
from pathlib import Path

TOKEN_FILE = Path(__file__).parent / "tenchat_token.json"


def save(token: str):
    token = token.strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    if len(token) < 20:
        print("❌  Токен слишком короткий — скопируй полностью")
        sys.exit(1)
    TOKEN_FILE.write_text(json.dumps({"token": token}, indent=2, ensure_ascii=False))
    print(f"✅  Токен сохранён → {TOKEN_FILE}")
    print(f"   Длина: {len(token)} символов")
    print()
    print("Проверь подключение:")
    print("  python3 tenchat_check.py")


if __name__ == "__main__":
    token = (
        sys.argv[1]
        if len(sys.argv) > 1
        else os.getenv("TENCHAT_TOKEN", "")
    )
    if not token:
        print("Использование:")
        print("  python3 tenchat_set_token.py <ТОКЕН>")
        print()
        print("Или вставь токен сюда (Enter для завершения):")
        token = input("> ").strip()

    save(token)
