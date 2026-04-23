import os
import io
import json
import time
import base64
import httpx
from PIL import Image
from dotenv import load_dotenv
from playwright.async_api import async_playwright
from tools.image_utils import fit_image

load_dotenv()

PINTEREST_EMAIL = os.getenv("PINTEREST_EMAIL")
PINTEREST_PASSWORD = os.getenv("PINTEREST_PASSWORD")
PINTEREST_USERNAME = os.getenv("PINTEREST_USERNAME")
PINTEREST_BOARD = os.getenv("PINTEREST_BOARD_NAME")
PINTEREST_APP_ID = os.getenv("PINTEREST_APP_ID")
PINTEREST_APP_SECRET = os.getenv("PINTEREST_APP_SECRET")
PINTEREST_ACCESS_TOKEN = os.getenv("PINTEREST_ACCESS_TOKEN")  # ручной токен из dev portal
CRED_ROOT = "/root/crossposting/pinterest_creds"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TOKEN_FILE = "/root/pinterest_token.json"
COOKIE_FILE = os.path.join(CRED_ROOT, "cookies.json")
COOKIE_TTL = 15 * 24 * 3600  # 15 дней


def _read_token_file() -> dict:
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE) as f:
            return json.load(f)
    return {}


def _save_token_file(data: dict):
    os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
    with open(TOKEN_FILE, "w") as f:
        json.dump(data, f, indent=2)


async def _refresh_access_token() -> str | None:
    """Обновляет access_token через refresh_token. Возвращает новый токен или None."""
    data = _read_token_file()
    refresh_token = data.get("refresh_token")
    if not refresh_token or not PINTEREST_APP_ID or not PINTEREST_APP_SECRET:
        return None

    credentials = base64.b64encode(f"{PINTEREST_APP_ID}:{PINTEREST_APP_SECRET}".encode()).decode()
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                "https://api.pinterest.com/v5/oauth/token",
                headers={
                    "Authorization": f"Basic {credentials}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={"grant_type": "refresh_token", "refresh_token": refresh_token},
                timeout=20,
            )
            tokens = r.json()

        if "access_token" in tokens:
            tokens.setdefault("refresh_token", refresh_token)  # сохраняем старый если не вернули новый
            tokens["obtained_at"] = int(time.time())
            _save_token_file(tokens)
            print("[PINTEREST] Access token refreshed")
            return tokens["access_token"]
    except Exception as e:
        print(f"[PINTEREST] Token refresh failed: {e}")
    return None


async def load_token() -> str | None:
    """
    Возвращает действующий access_token. Приоритет:
    1. PINTEREST_ACCESS_TOKEN в .env (токен из developer portal — используется как есть)
    2. TOKEN_FILE (/root/pinterest_token.json) — с проверкой срока и авторефрешем
    """
    # 1. Токен из переменной окружения — доверяем как есть, без проверки срока
    if PINTEREST_ACCESS_TOKEN:
        return PINTEREST_ACCESS_TOKEN

    # 2. Токен из файла (получен через OAuth-скрипт)
    data = _read_token_file()
    token = data.get("access_token")
    if not token:
        return None

    # Если токен сохранён без obtained_at (например, вставлен вручную) — доверяем
    if not data.get("obtained_at"):
        return token

    # Проверяем срок: пробуем рефреш за 1 день до истечения
    expires_in = data.get("expires_in", 2592000)  # default 30 дней
    if time.time() > data["obtained_at"] + expires_in - 86400:
        print("[PINTEREST] Access token expired, refreshing...")
        return await _refresh_access_token()  # None если refresh не удался

    return token


def resize_for_pinterest(image_bytes: bytes) -> bytes:
    return fit_image(image_bytes)


async def adapt_pinterest_text(text: str) -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            json={
                "model": "gpt-4.1-mini",
                "messages": [
                    {"role": "system", "content": (
                        "Из текста создай поля для Pinterest.\n"
                        "TITLE: до 100 символов, цепляющий заголовок\n"
                        "DESC: до 500 символов, описание + 5 хэштегов\n"
                        "Формат строго:\nTITLE: ...\nDESC: ..."
                    )},
                    {"role": "user", "content": text or "Новый пост"}
                ],
                "temperature": 0.9
            },
            timeout=20
        )
    content = r.json()["choices"][0]["message"]["content"]
    lines = [l for l in content.strip().split("\n") if l.strip()]
    title = lines[0].replace("TITLE:", "").strip() if lines else ""
    desc = lines[1].replace("DESC:", "").strip() if len(lines) > 1 else ""
    return {"title": title, "description": desc}


# ─── Playwright (email/password) ──────────────────────────────────────────────

async def _login(page, context) -> bool:
    """Авторизация через форму. Сохраняет куки. Возвращает True при успехе."""
    print("[PINTEREST] Opening login page...")
    
    # Пробуем мобильную версию - меньше защиты
    await page.goto("https://www.pinterest.com/login/", wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(5000)
    
    # Проверяем есть ли уже форма входа
    email_sel = 'input[id="email"], input[name="email"], input[type="email"]'
    
    # Если не найден, пробуем другой селектор
    if await page.locator(email_sel).count() == 0:
        email_sel = '#email, input[type="email"]'
    
    try:
        await page.locator(email_sel).first.wait_for(state="visible", timeout=10000)
    except:
        # Страница может требовать JavaScript
        print("[PINTEREST] Waiting for page to load...")
        await page.wait_for_timeout(5000)
    
    await page.locator(email_sel).first.fill(PINTEREST_EMAIL)
    await page.wait_for_timeout(1000)

    pwd_sel = '#password, input[type="password"]'
    await page.locator(pwd_sel).first.fill(PINTEREST_PASSWORD)
    await page.wait_for_timeout(1000)

    # Клик по кнопке входа
    await page.keyboard.press("Enter")
    await page.wait_for_timeout(15000)

    current_url = page.url
    if "login" in current_url:
        # Делаем скриншот для отладки
        print(f"[PINTEREST] Login failed, URL: {current_url}")
        return False

    print(f"[PINTEREST] Login OK → {current_url}")
    os.makedirs(CRED_ROOT, exist_ok=True)
    with open(COOKIE_FILE, "w") as f:
        json.dump(await context.cookies(), f)
    return True


async def _ensure_logged_in(page, context) -> bool:
    """Загружает куки или выполняет логин. Возвращает True если авторизованы."""
    cookie_ok = False
    if os.path.exists(COOKIE_FILE) and time.time() - os.path.getmtime(COOKIE_FILE) < COOKIE_TTL:
        with open(COOKIE_FILE) as f:
            await context.add_cookies(json.load(f))
        cookie_ok = True
        print("[PINTEREST] Loaded cached cookies")

    # Пробуем мобильную версию - она менее защищена
    await page.goto("https://www.pinterest.com/", wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(5000)

    # Проверяем различные признаки выхода
    login_button = await page.locator('[data-test-id="header-login-button"], a[href="/login/"]').count()
    logged_out = (
        "login" in page.url
        or login_button > 0
        or not cookie_ok
    )

    if logged_out:
        print("[PINTEREST] Not authenticated, logging in...")
        login_result = await _login(page, context)
        if not login_result:
            return False
        return True

    return True


async def post_to_pinterest_playwright(image_paths: list, text: str) -> dict:
    """
    Публикует пин или карусель через Playwright.
    При 2+ изображениях Pinterest автоматически создаёт карусель.
    """
    os.makedirs(CRED_ROOT, exist_ok=True)

    tmp_paths = []
    for i, path in enumerate(image_paths[:5]):
        with open(path, "rb") as f:
            resized = resize_for_pinterest(f.read())
        tmp_path = f"/tmp/pinterest_pin_{i}.jpg"
        with open(tmp_path, "wb") as f:
            f.write(resized)
        tmp_paths.append(tmp_path)

    print(f"[PINTEREST] Prepared {len(tmp_paths)} image(s)")
    adapted = await adapt_pinterest_text(text)

    try:
        async with async_playwright() as pw:
            # Используем Chrome (не Chromium) - лучше маскировка
            browser = await pw.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage", 
                    "--disable-blink-features=AutomationControlled",
                    "--disable-features=TranslateUI",
                    "--disable-ipc-flooding-protection",
                    "--disable-renderer-backgrounding",
                    "--enable-features=NetworkService,NetworkServiceInProcess",
                ]
            )
            context = await browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                locale="ru-RU,ru",
                timezone_id="Europe/Moscow",
                permissions=["geolocation", "notifications"],
            )
            
            page = await context.new_page()
            
            # Маскируем webdriver и другие признаки автоматизации
            await page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                Object.defineProperty(navigator, 'languages', {get: () => ['ru-RU', 'ru', 'en-US', 'en']});
                window.chrome = {runtime: {}};
            """)
            
            # Удаляем куки перед новой попыткой
            if os.path.exists(COOKIE_FILE):
                os.remove(COOKIE_FILE)

            if not await _ensure_logged_in(page, context):
                await browser.close()
                return {"status": "error", "error": "Pinterest login failed"}

            # Переходим в конструктор пинов
            print("[PINTEREST] Opening pin builder...")
            await page.goto(
                "https://www.pinterest.com/pin-builder/",
                wait_until="domcontentloaded",
                timeout=60000
            )
            await page.wait_for_timeout(4000)

            # Загружаем изображения
            file_input = page.locator('input[type="file"]').first
            await file_input.wait_for(state="attached", timeout=20000)
            await file_input.set_input_files(tmp_paths)
            print("[PINTEREST] Files submitted, waiting for preview...")
            await page.wait_for_timeout(6000)

            # Если загружено 2+ файлов — Pinterest покажет выбор типа (карусель/коллаж).
            # Ищем кнопку «Carousel» и кликаем по ней, если она есть.
            carousel_btn = page.locator(
                'button:has-text("Carousel"), '
                '[data-test-id="carousel-type-button"], '
                'div[role="button"]:has-text("Carousel")'
            ).first
            if await carousel_btn.count() > 0:
                await carousel_btn.click()
                await page.wait_for_timeout(2000)
                print("[PINTEREST] Carousel mode selected")

            # Заголовок
            title_sel = (
                '[data-test-id="pin-draft-title"] textarea, '
                '[data-test-id="pin-draft-title"] input, '
                'textarea[placeholder*="itle"], '
                'input[placeholder*="itle"]'
            )
            title_el = page.locator(title_sel).first
            if await title_el.count() > 0:
                await title_el.click()
                await title_el.fill(adapted["title"][:100])
                print(f"[PINTEREST] Title: {adapted['title'][:50]}...")

            # Описание
            desc_sel = (
                '[data-test-id="pin-draft-description"] textarea, '
                'textarea[placeholder*="escription"], '
                'textarea[placeholder*="ell everyone"]'
            )
            desc_el = page.locator(desc_sel).first
            if await desc_el.count() > 0:
                await desc_el.click()
                await desc_el.fill(adapted["description"][:500])
                print("[PINTEREST] Description set")

            # Выбор доски
            if PINTEREST_BOARD:
                board_btn = page.locator('[data-test-id="board-dropdown-select-button"]').first
                if await board_btn.count() > 0:
                    await board_btn.click()
                    await page.wait_for_timeout(1500)
                    # Пробуем найти доску по тексту
                    board_opt = page.locator(
                        f'[data-test-id="board-row"] >> text="{PINTEREST_BOARD}"'
                    ).first
                    if await board_opt.count() == 0:
                        board_opt = page.locator(f'text="{PINTEREST_BOARD}"').first
                    if await board_opt.count() > 0:
                        await board_opt.click()
                        await page.wait_for_timeout(1000)
                        print(f"[PINTEREST] Board selected: {PINTEREST_BOARD}")

            # Публикуем
            publish_sel = (
                '[data-test-id="board-dropdown-save-button"], '
                'button[data-test-id="save-pin-button"], '
                'button:has-text("Publish"), '
                'button:has-text("Save")'
            )
            publish_btn = page.locator(publish_sel).first
            await publish_btn.wait_for(state="visible", timeout=15000)
            await publish_btn.click()
            await page.wait_for_timeout(6000)

            print(f"[PINTEREST] Done. URL: {page.url}")
            await browser.close()

    finally:
        for p in tmp_paths:
            try:
                os.remove(p)
            except Exception:
                pass

    return {"status": "ok", "method": "playwright"}


# ─── Pinterest API (если есть access token) ───────────────────────────────────

async def get_board_id_by_name(token: str, board_name: str) -> str | None:
    async with httpx.AsyncClient() as client:
        r = await client.get(
            "https://api.pinterest.com/v5/boards",
            headers={"Authorization": f"Bearer {token}"},
            params={"page_size": 100},
            timeout=15
        )
        for board in r.json().get("items", []):
            if board["name"].lower() == board_name.lower():
                return board["id"]
    return None


async def _upload_image_api(image_bytes: bytes, token: str) -> str:
    """Загружает изображение в Pinterest API"""
    import base64
    # Используем base64 вместо media endpoint (работает в Trial)
    image_b64 = base64.b64encode(image_bytes).decode('utf-8')
    return image_b64


async def _post_pin_api(images_bytes: list, text: str, token: str, board_id: str) -> dict:
    """Создаёт пин через Pinterest API с base64 изображениями"""
    import base64
    adapted = await adapt_pinterest_text(text)
    
    # Конвертируем изображения в URL-safe base64 (без переносов строк)
    images_b64 = []
    for img in images_bytes[:5]:
        resized = resize_for_pinterest(img)
        b64 = base64.b64encode(resized).decode('utf-8').replace('\n', '').replace('\r', '')
        images_b64.append(b64)
    
    async with httpx.AsyncClient() as client:
        if len(images_b64) == 1:
            r = await client.post(
                "https://api.pinterest.com/v5/pins",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={
                    "board_id": board_id,
                    "title": adapted["title"][:100],
                    "description": adapted["description"][:500],
                    "media_source": {
                        "source_type": "image_base64",
                        "content_type": "image/jpeg",
                        "data": images_b64[0]
                    }
                },
                timeout=30
            )
        else:
            # Карусель через multiple_image_base64
            items = []
            for img_b64 in images_b64:
                items.append({
                    "content_type": "image/jpeg",
                    "data": img_b64,
                    "title": adapted["title"][:100],
                    "description": adapted["description"][:500]
                })
            
            r = await client.post(
                "https://api.pinterest.com/v5/pins",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={
                    "board_id": board_id,
                    "title": adapted["title"][:100],
                    "description": adapted["description"][:500],
                    "media_source": {
                        "source_type": "multiple_image_base64",
                        "items": items
                    }
                },
                timeout=30
            )
    
    return r.json()


async def _post_pin_api(images_bytes: list, text: str, token: str, board_id: str) -> dict:
    adapted = await adapt_pinterest_text(text)
    media_ids = [await _upload_image_api(img, token) for img in images_bytes[:5]]

    if len(media_ids) == 1:
        media_source = {"source_type": "media_id", "media_id": media_ids[0]}
    else:
        items = [{"title": adapted["title"], "description": adapted["description"]}
                 for _ in media_ids]
        media_source = {
            "source_type": "multiple_media_ids",
            "media_ids": media_ids,
            "items": items
        }

    async with httpx.AsyncClient() as client:
        r = await client.post(
            "https://api.pinterest.com/v5/pins",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={
                "board_id": board_id,
                "title": adapted["title"],
                "description": adapted["description"],
                "media_source": media_source
            },
            timeout=30
        )
    return r.json()


# ─── Главная точка входа ──────────────────────────────────────────────────────

async def post_to_pinterest(image_paths: list, text: str) -> dict:
    """
    Публикует пин или карусель в Pinterest.
    
    Пока недоступно - требуется Production Access.
    Возвращает информацию для ручной публикации.
    """
    token = await load_token()
    
    if not token:
        return {"status": "error", "error": "Нет токена Pinterest"}

    try:
        board_id = await get_board_id_by_name(token, PINTEREST_BOARD)
        if not board_id:
            return {"status": "error", "error": f"Доска '{PINTEREST_BOARD}' не найдена"}
        
        # Сохраняем изображение локально для ручной публикации
        import base64
        from datetime import datetime
        from pathlib import Path
        
        save_dir = Path("/root/crossposting/pinterest_pending")
        save_dir.mkdir(exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Сохраняем все изображения
        saved_files = []
        for i, path in enumerate(image_paths):
            with open(path, "rb") as f:
                img_data = f.read()
            
            filename = f"pin_{timestamp}_{i}.jpg"
            save_path = save_dir / filename
            with open(save_path, "wb") as f:
                f.write(img_data)
            saved_files.append(str(save_path))
        
        # Адаптируем текст
        adapted = await adapt_pinterest_text(text)
        
        return {
            "status": "pending", 
            "method": "manual",
            "message": "Требуется Production Access. Файлы сохранены для ручной публикации.",
            "board_url": f"https://www.pinterest.com/{os.getenv('PINTEREST_USERNAME')}/",
            "saved_files": saved_files,
            "title": adapted["title"],
            "description": adapted["description"]
        }
        
    except Exception as e:
        return {"status": "error", "error": f"Ошибка: {e}"}
