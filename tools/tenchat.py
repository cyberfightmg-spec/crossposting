"""
TenChat: гибридный клиент
  1. Первый раз: Playwright логинится, перехватывает Bearer-токен + API-эндпоинты
  2. Следующие разы: чистый httpx с сохранённым токеном (быстро, стабильно)
  3. Если 401 / токен протух: автоматически обновляет через Playwright
"""
import os
import json
import asyncio
import logging
import tempfile
import httpx
from pathlib import Path
from typing import List, Union
from playwright.async_api import async_playwright, BrowserContext, Page

log = logging.getLogger("crosspost.tenchat")

TENCHAT_PHONE      = os.getenv("TENCHAT_PHONE", "")
BASE_DIR           = Path(__file__).parent.parent
STATE_FILE         = BASE_DIR / "tenchat_session.json"
TOKEN_FILE         = BASE_DIR / "tenchat_token.json"
API_FILE           = BASE_DIR / "tenchat_api.json"

# ─── Хранилище токена и API-описания ──────────────────────────────────────────

def _load_token() -> dict:
    try:
        return json.loads(TOKEN_FILE.read_text()) if TOKEN_FILE.exists() else {}
    except Exception:
        return {}


def _save_token(token: str, extra: dict | None = None):
    data = {"token": token, **(extra or {})}
    TOKEN_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    log.info(f"TenChat: токен сохранён → {TOKEN_FILE}")


def _load_api() -> dict:
    try:
        return json.loads(API_FILE.read_text()) if API_FILE.exists() else {}
    except Exception:
        return {}


def _save_api(info: dict):
    API_FILE.write_text(json.dumps(info, ensure_ascii=False, indent=2))
    log.info(f"TenChat: API-описание сохранено → {API_FILE}")


def has_credentials() -> bool:
    return bool(TENCHAT_PHONE)


# ─── Перехват токена из браузерных запросов ───────────────────────────────────

class _TokenCapture:
    """Перехватывает Bearer-токен и POST-эндпоинты из сетевых запросов Playwright."""

    def __init__(self):
        self.token: str | None = None
        self.post_endpoints: list[dict] = []

    def on_request(self, request):
        auth = request.headers.get("authorization", "")
        if auth.startswith("Bearer ") and not self.token:
            self.token = auth.split(" ", 1)[1]
            log.info(f"TenChat: Bearer-токен перехвачен (len={len(self.token)})")

    def on_response_post(self, response):
        if response.request.method == "POST" and response.status in (200, 201):
            url = response.url
            # Ищем эндпоинты публикации (обычно содержат "post", "feed", "article")
            keywords = ("post", "feed", "article", "publication", "create", "wall")
            if any(k in url.lower() for k in keywords):
                self.post_endpoints.append({
                    "url": url,
                    "status": response.status,
                })
                log.info(f"TenChat: POST-эндпоинт найден: {url}")


# ─── Playwright: логин и разовая публикация ───────────────────────────────────

async def _playwright_login_and_capture(capture: _TokenCapture) -> BrowserContext | None:
    """
    Запускает браузер, восстанавливает сессию или сообщает о необходимости ручного входа.
    Подключает перехват токена. Возвращает context или None при ошибке.
    """
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-blink-features=AutomationControlled",
        ],
    )

    storage = str(STATE_FILE) if STATE_FILE.exists() else None
    context = await browser.new_context(
        storage_state=storage,
        viewport={"width": 1280, "height": 900},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
    )
    context.on("request", capture.on_request)
    context.on("response", capture.on_response_post)
    return context, browser, pw


async def _check_logged_in(page: Page) -> bool:
    await page.goto("https://tenchat.ru/feed", wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(3000)
    url = page.url
    if "/auth" in url or "/login" in url or "sign" in url:
        return False
    # Ждём характерные элементы ленты
    try:
        await page.wait_for_selector(
            '[data-testid="create-post-btn"], button:has-text("Написать"), .feed-container',
            timeout=8000,
        )
        return True
    except Exception:
        return "auth" not in page.url


async def _playwright_post(
    page: Page, context: BrowserContext, text: str, image_paths: list[str]
) -> bool:
    """Публикует пост через браузер. Возвращает True при успехе."""

    # Открываем форму создания поста
    selectors_create = [
        '[data-testid="create-post-btn"]',
        'button:has-text("Написать")',
        'a:has-text("Написать")',
        '[class*="create"][class*="post"]',
        '[class*="NewPost"]',
    ]
    create_btn = None
    for sel in selectors_create:
        try:
            create_btn = await page.wait_for_selector(sel, timeout=4000, state="visible")
            if create_btn:
                break
        except Exception:
            continue

    if not create_btn:
        await page.screenshot(path=str(BASE_DIR / "tenchat_debug.png"))
        log.error("TenChat: кнопка создания поста не найдена, сохранён скриншот")
        return False

    await create_btn.click()
    await page.wait_for_timeout(1500)

    # Вводим текст
    text_selectors = [
        'div[contenteditable="true"]',
        'textarea[placeholder]',
        '[data-testid="post-text-input"]',
    ]
    for sel in text_selectors:
        try:
            el = await page.wait_for_selector(sel, timeout=5000, state="visible")
            if el:
                await el.click()
                await el.fill(text)
                break
        except Exception:
            continue

    await page.wait_for_timeout(500)

    # Загружаем изображения если есть
    if image_paths:
        file_input_sel = 'input[type="file"][accept*="image"], input[type="file"]'
        try:
            file_input = await page.wait_for_selector(file_input_sel, timeout=6000)
            if file_input:
                await file_input.set_input_files(image_paths[:9])
                await page.wait_for_timeout(3000)
        except Exception as e:
            log.warning(f"TenChat: загрузка файлов не удалась — {e}")

    # Публикуем
    publish_selectors = [
        'button:has-text("Опубликовать")',
        '[data-testid="publish-btn"]',
        'button[type="submit"]:has-text("Опубликовать")',
    ]
    for sel in publish_selectors:
        try:
            btn = await page.wait_for_selector(sel, timeout=6000, state="visible")
            if btn:
                await btn.click()
                await page.wait_for_timeout(4000)
                log.info("TenChat: пост опубликован через браузер ✅")
                # Сохраняем обновлённую сессию
                await context.storage_state(path=str(STATE_FILE))
                return True
        except Exception:
            continue

    log.error("TenChat: кнопка публикации не найдена")
    return False


# ─── httpx: прямое API-постинг ────────────────────────────────────────────────

async def _api_post(token: str, text: str, image_paths: list[str]) -> dict | None:
    """
    Публикует пост через перехваченный API.
    Структура эндпоинта и тела сохранены в tenchat_api.json после первой
    публикации через браузер.
    """
    api = _load_api()
    endpoint = api.get("create_post_url")
    if not endpoint:
        log.info("TenChat: API-эндпоинт ещё не обнаружен, используем браузер")
        return None

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Origin": "https://tenchat.ru",
        "Referer": "https://tenchat.ru/feed",
    }

    # Базовая структура тела (уточняется после первой публикации)
    body_template = api.get("body_template", {})
    body = {**body_template, "text": text}

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(endpoint, json=body, headers=headers)
        if r.status_code in (200, 201):
            log.info(f"TenChat: пост опубликован через API ✅ ({r.status_code})")
            return r.json()
        if r.status_code in (401, 403):
            log.warning(f"TenChat: токен устарел ({r.status_code})")
            return None  # сигнал для обновления токена
        log.error(f"TenChat: API ошибка {r.status_code}: {r.text[:300]}")
        return None
    except Exception as e:
        log.error(f"TenChat: httpx ошибка — {e}")
        return None


# ─── Главная функция публикации ───────────────────────────────────────────────

async def _post_with_refresh(
    text: str,
    image_paths: list[str],
    force_browser: bool = False,
) -> dict:
    """
    Пробует httpx с сохранённым токеном.
    Если нет токена / 401 / force_browser — логинится через Playwright,
    перехватывает новый токен и публикует.
    """
    # 1. Попытка через httpx
    if not force_browser:
        token_data = _load_token()
        token = token_data.get("token")
        if token:
            result = await _api_post(token, text, image_paths)
            if result is not None:
                return {"status": "ok", "platform": "tenchat", "method": "api", "data": result}
            # 401 — токен протух, идём обновлять
            log.info("TenChat: токен протух, обновляем через браузер")

    # 2. Playwright: логин + публикация + перехват нового токена
    capture = _TokenCapture()
    context, browser, pw = await _playwright_login_and_capture(capture)
    try:
        page = await context.new_page()
        page.on("request", capture.on_request)

        logged_in = await _check_logged_in(page)
        if not logged_in:
            log.error(
                "TenChat: сессия устарела — нужно войти вручную.\n"
                f"Удали {STATE_FILE} и запусти: python3 tools/tenchat_login.py"
            )
            return {"status": "error", "error": "TenChat session expired, manual login required"}

        # Публикуем через UI, одновременно перехватываем токен
        ok = await _playwright_post(page, context, text, image_paths)

        # Сохраняем перехваченный токен
        if capture.token:
            _save_token(capture.token)

        # Сохраняем обнаруженные POST-эндпоинты для будущих API-вызовов
        if capture.post_endpoints:
            api_data = _load_api()
            # Берём первый подходящий эндпоинт как кандидата
            api_data["create_post_url"] = capture.post_endpoints[0]["url"]
            api_data["all_post_endpoints"] = capture.post_endpoints
            _save_api(api_data)
            log.info(f"TenChat: обнаружено {len(capture.post_endpoints)} POST-эндпоинт(ов)")

        return {
            "status": "ok" if ok else "error",
            "platform": "tenchat",
            "method": "playwright",
        }
    finally:
        await browser.close()
        await pw.stop()


# ─── Публичные функции (вызываются из main.py) ────────────────────────────────

async def post_text_tenchat(text: str, title: str = "") -> dict:
    full_text = f"{title}\n\n{text}" if title else text
    return await _post_with_refresh(full_text, [])


async def post_photo_tenchat(
    image_paths: List[Union[str, bytes]], caption: str = "", title: str = ""
) -> dict:
    # Байты → временные файлы
    tmp_files = []
    real_paths = []
    try:
        for img in image_paths:
            if isinstance(img, bytes):
                f = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
                f.write(img)
                f.close()
                tmp_files.append(f.name)
                real_paths.append(f.name)
            else:
                real_paths.append(str(img))

        full_text = f"{title}\n\n{caption}" if title else caption
        return await _post_with_refresh(full_text, real_paths)
    finally:
        for p in tmp_files:
            try:
                os.unlink(p)
            except Exception:
                pass


async def post_video_tenchat(video_bytes: bytes, caption: str = "", title: str = "") -> dict:
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
        f.write(video_bytes)
        tmp_path = f.name
    try:
        full_text = f"{title}\n\n{caption}" if title else caption
        return await _post_with_refresh(full_text, [tmp_path])
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
