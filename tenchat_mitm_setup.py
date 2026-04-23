"""
Перехват Bearer-токена TenChat через HTTPS-прокси.
Только стандартная библиотека Python + openssl (уже на сервере).

Запусти на сервере:
  python3 tenchat_mitm_setup.py

Скрипт напечатает 4 ADB-команды. Выполни их на виртуальном телефоне
и открой TenChat — токен сохранится в tenchat_token.json автоматически.
"""
import os, ssl, sys, json, socket, threading, subprocess, socketserver
from http.server import BaseHTTPRequestHandler
from pathlib import Path

PROXY_PORT = 8080
BASE_DIR   = Path(__file__).parent
TOKEN_FILE = BASE_DIR / "tenchat_token.json"
CERTS_DIR  = BASE_DIR / "_mitm_certs"

_found_token: str | None = None
_ca_key: Path
_ca_crt: Path


# ─── Cert helpers ─────────────────────────────────────────────────────────────

def _run(*cmd, input=None):
    r = subprocess.run(cmd, capture_output=True, text=True, input=input)
    if r.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed: {r.stderr[:200]}")
    return r.stdout


def setup_ca() -> tuple[Path, Path]:
    CERTS_DIR.mkdir(parents=True, exist_ok=True)
    ca_key = CERTS_DIR / "ca.key"
    ca_crt = CERTS_DIR / "ca.crt"
    if not ca_key.exists():
        _run("openssl", "genrsa", "-out", str(ca_key), "2048")
    if not ca_crt.exists():
        _run("openssl", "req", "-new", "-x509", "-days", "3650",
             "-key", str(ca_key), "-out", str(ca_crt),
             "-subj", "/C=RU/O=MITM/CN=MITM Proxy CA")
    return ca_key, ca_crt


def cert_hash(crt: Path) -> str:
    out = _run("openssl", "x509", "-inform", "PEM", "-subject_hash_old", "-in", str(crt))
    return out.strip().splitlines()[0]


def host_cert(hostname: str) -> tuple[Path, Path]:
    key = CERTS_DIR / f"{hostname}.key"
    crt = CERTS_DIR / f"{hostname}.crt"
    if crt.exists():
        return key, crt
    _run("openssl", "genrsa", "-out", str(key), "2048")
    csr = CERTS_DIR / f"{hostname}.csr"
    _run("openssl", "req", "-new", "-key", str(key), "-out", str(csr),
         "-subj", f"/CN={hostname}")
    _run("openssl", "x509", "-req", "-days", "365",
         "-in", str(csr), "-CA", str(_ca_crt), "-CAkey", str(_ca_key),
         "-CAcreateserial", "-out", str(crt),
         "-extensions", "v3_req",
         "-extfile", "/dev/stdin",
         input=f"[v3_req]\nsubjectAltName=DNS:{hostname}")
    return key, crt


# ─── Token detection ──────────────────────────────────────────────────────────

def _check_data(data: bytes, hostname: str) -> None:
    global _found_token
    if _found_token:
        return
    try:
        text = data.decode("utf-8", errors="ignore")
    except Exception:
        return
    for line in text.replace("\r\n", "\n").split("\n"):
        low = line.lower()
        if low.startswith("authorization: bearer "):
            token = line.split(" ", 2)[2].strip()
            if len(token) >= 20:
                _found_token = token
                print(f"\n{'='*55}")
                print("  ✅  ТОКЕН ПЕРЕХВАЧЕН!")
                print(f"  Host : {hostname}")
                print(f"  Token: {token[:30]}...{token[-10:]}")
                TOKEN_FILE.write_text(
                    json.dumps({"token": token}, indent=2, ensure_ascii=False)
                )
                print(f"  Файл : {TOKEN_FILE}")
                print(f"{'='*55}")
                print("\nТеперь:")
                print("  1. Закрой TenChat на телефоне")
                print("  2. В ADB Commands выполни:")
                print("       settings delete global http_proxy")
                print("  3. Нажми Ctrl+C здесь чтобы остановить прокси\n")
                return


# ─── Proxy request handler ────────────────────────────────────────────────────

class _ProxyHandler(BaseHTTPRequestHandler):

    def log_message(self, *_):
        pass  # тихий режим

    # Раздаём CA-сертификат по GET /cert/pem
    def do_GET(self):
        if self.path.rstrip("/") == "/cert/pem":
            data = _ca_crt.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/x-pem-file")
            self.send_header("Content-Disposition",
                             "attachment; filename=mitm-ca.pem")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        else:
            self.send_error(404)

    # HTTPS CONNECT → SSL MITM tunnel
    def do_CONNECT(self):
        host_port = self.path
        if ":" in host_port:
            hostname, _, port_s = host_port.rpartition(":")
            port = int(port_s)
        else:
            hostname, port = host_port, 443

        # Ответ "туннель установлен"
        self.send_response(200, "Connection established")
        self.end_headers()
        try:
            self.wfile.flush()
        except Exception:
            return

        raw_sock = self.connection

        # Оборачиваем клиентский сокет в SSL (наш поддельный сертификат)
        try:
            key, crt = host_cert(hostname)
            ctx_srv = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx_srv.load_cert_chain(str(crt), str(key))
            client_ssl = ctx_srv.wrap_socket(raw_sock, server_side=True)
        except Exception:
            return

        # Подключаемся к настоящему серверу
        try:
            real_sock = socket.create_connection((hostname, port), timeout=15)
            ctx_cli = ssl.create_default_context()
            ctx_cli.check_hostname = False
            ctx_cli.verify_mode = ssl.CERT_NONE
            server_ssl = ctx_cli.wrap_socket(real_sock, server_hostname=hostname)
        except Exception:
            try:
                client_ssl.close()
            except Exception:
                pass
            return

        # Ретрансляция: клиент → сервер (с проверкой токена)
        def fwd(src, dst, inspect: bool):
            try:
                while True:
                    chunk = src.recv(8192)
                    if not chunk:
                        break
                    if inspect:
                        _check_data(chunk, hostname)
                    dst.sendall(chunk)
            except Exception:
                pass
            finally:
                for s in (src, dst):
                    try:
                        s.shutdown(socket.SHUT_WR)
                    except Exception:
                        pass

        t1 = threading.Thread(target=fwd, args=(client_ssl, server_ssl, True),  daemon=True)
        t2 = threading.Thread(target=fwd, args=(server_ssl, client_ssl, False), daemon=True)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        for s in (client_ssl, server_ssl):
            try:
                s.close()
            except Exception:
                pass


class _ThreadedServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


# ─── Entry point ──────────────────────────────────────────────────────────────

def _server_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "YOUR_SERVER_IP"


def main():
    global _ca_key, _ca_crt

    print("=" * 55)
    print("  TenChat — перехват токена (HTTPS прокси)")
    print("=" * 55)

    _ca_key, _ca_crt = setup_ca()
    h = cert_hash(_ca_crt)
    ip = _server_ip()

    print(f"\nIP сервера     : {ip}")
    print(f"Хэш сертификата: {h}")
    print()
    print("=" * 55)
    print("  Выполни по очереди в ADB Commands на телефоне:")
    print("=" * 55)
    print()
    print("Команда 1 — включить прокси:")
    print(f"  settings put global http_proxy {ip}:{PROXY_PORT}")
    print()
    print("Команда 2 — скачать сертификат:")
    print(f"  curl -o /sdcard/mitm.pem http://{ip}:{PROXY_PORT}/cert/pem")
    print()
    print("Команда 3 — установить сертификат:")
    print(f"  mount -o rw,remount /system && cp /sdcard/mitm.pem /system/etc/security/cacerts/{h}.0 && chmod 644 /system/etc/security/cacerts/{h}.0 && mount -o ro,remount /system")
    print()
    print("Команда 4 — перезагрузить:")
    print("  reboot")
    print()
    print("После перезагрузки открой TenChat и жди — токен появится здесь.")
    print("=" * 55)
    print()

    server = _ThreadedServer(("0.0.0.0", PROXY_PORT), _ProxyHandler)
    print(f"Прокси запущен на порту {PROXY_PORT}. Жду подключения...\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass

    if _found_token:
        print(f"\n✅  Токен сохранён: {TOKEN_FILE}")
    else:
        print("\n⚠️   Токен не перехвачен.")


if __name__ == "__main__":
    main()
