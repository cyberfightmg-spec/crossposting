"""
Перехват Bearer-токена TenChat через HTTPS-прокси.

Запусти на сервере:
  python3 tenchat_mitm_setup.py

Скрипт напечатает точные ADB-команды для виртуального телефона.
Токен сохранится в tenchat_token.json автоматически.
"""
import os
import sys
import json
import socket
import subprocess
import time
from pathlib import Path

PROXY_PORT = 8080
BASE_DIR   = Path(__file__).parent
TOKEN_FILE = BASE_DIR / "tenchat_token.json"
CERT_DIR   = Path.home() / ".mitmproxy"


def get_server_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "YOUR_SERVER_IP"


def ensure_mitmproxy():
    try:
        import mitmproxy  # noqa: F401
        return True
    except ImportError:
        print("Устанавливаю mitmproxy...")
        result = subprocess.run([sys.executable, "-m", "pip", "install", "mitmproxy", "-q"])
        return result.returncode == 0


def generate_certs():
    """Запускаем mitmdump на 2 секунды чтобы сгенерировать сертификаты."""
    cert_file = CERT_DIR / "mitmproxy-ca-cert.pem"
    if cert_file.exists():
        return True
    print("Генерирую сертификаты прокси...")
    p = subprocess.Popen(
        ["mitmdump", "-p", str(PROXY_PORT), "--quiet"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(3)
    p.terminate()
    p.wait()
    return cert_file.exists()


def get_cert_hash() -> str | None:
    cert_file = CERT_DIR / "mitmproxy-ca-cert.pem"
    if not cert_file.exists():
        return None
    result = subprocess.run(
        ["openssl", "x509", "-inform", "PEM", "-subject_hash_old", "-in", str(cert_file)],
        capture_output=True, text=True,
    )
    lines = result.stdout.strip().split("\n")
    return lines[0].strip() if lines else None


def print_adb_instructions(server_ip: str, cert_hash: str):
    print()
    print("=" * 60)
    print("  Выполни эти команды в ADB Commands на виртуальном телефоне")
    print("=" * 60)
    print()
    print("▶ Команда 1 — включить прокси:")
    print(f"   settings put global http_proxy {server_ip}:{PROXY_PORT}")
    print()
    print("▶ Команда 2 — скачать сертификат:")
    print(f"   curl -o /sdcard/mitm.pem http://{server_ip}:{PROXY_PORT}/cert/pem")
    print()
    print("▶ Команда 3 — установить сертификат (root):")
    print(f"   mount -o rw,remount /system && cp /sdcard/mitm.pem /system/etc/security/cacerts/{cert_hash}.0 && chmod 644 /system/etc/security/cacerts/{cert_hash}.0 && mount -o ro,remount /system")
    print()
    print("▶ Команда 4 — перезагрузить телефон:")
    print("   reboot")
    print()
    print("▶ После перезагрузки: запусти TenChat и подожди 5 секунд")
    print()
    print("=" * 60)
    print("  Токен появится здесь автоматически и сохранится в:")
    print(f"  {TOKEN_FILE}")
    print("=" * 60)
    print()


# ─── mitmproxy addon ──────────────────────────────────────────────────────────

ADDON_CODE = '''
import json
import logging
from pathlib import Path
from mitmproxy import http

TOKEN_FILE = Path("{token_file}")
found = False

def request(flow: http.HTTPFlow) -> None:
    global found
    if found:
        return
    host = flow.request.pretty_host
    if "gostinder" not in host and "tenchat" not in host:
        return
    auth = flow.request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return
    token = auth.split(" ", 1)[1].strip()
    if len(token) < 20:
        return
    found = True
    print()
    print("✅  ТОКЕН ПЕРЕХВАЧЕН!")
    print(f"   Host: {{host}}")
    print(f"   Token: {{token[:30]}}...{{token[-10:]}}")
    TOKEN_FILE.write_text(json.dumps({{"token": token}}, indent=2, ensure_ascii=False))
    print(f"   Сохранён: {{TOKEN_FILE}}")
    print()
    print("Можешь закрыть TenChat и остановить прокси (Ctrl+C).")
    print("Удали прокси с телефона: settings delete global http_proxy")
'''


def main():
    print("=" * 60)
    print("  TenChat — перехват токена через HTTPS-прокси")
    print("=" * 60)

    # Зависимости
    if not ensure_mitmproxy():
        print("❌  Не удалось установить mitmproxy")
        sys.exit(1)

    # Генерируем сертификат
    if not generate_certs():
        print("❌  Не удалось сгенерировать сертификаты")
        sys.exit(1)

    cert_hash = get_cert_hash()
    if not cert_hash:
        print("❌  Не удалось получить хэш сертификата")
        sys.exit(1)

    server_ip = get_server_ip()
    print(f"IP сервера: {server_ip}")
    print(f"Хэш сертификата: {cert_hash}")

    # Записываем addon-скрипт
    addon_path = BASE_DIR / "_tenchat_mitm_addon.py"
    addon_path.write_text(ADDON_CODE.format(token_file=str(TOKEN_FILE)))

    # Печатаем инструкции
    print_adb_instructions(server_ip, cert_hash)

    print("Запускаю прокси на порту 8080... (ожидаю токен)")
    print("Нажми Ctrl+C чтобы остановить.\n")

    # Запускаем mitmdump
    os.execvp("mitmdump", [
        "mitmdump",
        "-p", str(PROXY_PORT),
        "-s", str(addon_path),
        "--ssl-insecure",
    ])


if __name__ == "__main__":
    main()
