"""
TenChat posting via VMOS Cloud virtual phone (uiautomator2 over ADB).

Setup:
  pip install uiautomator2

Connection string from VMOS Cloud → Open Cloud Phone → Local Debugging:
  VMOS_ADB=1.2.3.4:5555

UI flow (as described):
  1. Scroll up  → "Добавить" button appears at bottom
  2. Tap "Добавить"
  3. Tap "Создать запись"
  4. Enter text (+ attach images)
  5. Tap "Опубликовать"
"""
import os
import asyncio
import logging
import subprocess
import tempfile
from typing import List, Union

log = logging.getLogger("crosspost.tenchat_vmos")

VMOS_ADB     = os.getenv("VMOS_ADB", "")          # e.g. "1.2.3.4:5555"
TENCHAT_PKG  = os.getenv("TENCHAT_PKG", "ru.gostinder")  # TenChat = "ГосТиндер"

_BTN_ADD        = "Добавить"
_BTN_CREATE     = "Создать запись"
_BTN_PUBLISH    = "Опубликовать"
_SCREENSHOT_PATH = "/tmp/tenchat_vmos_debug.png"


def _device():
    """Return connected uiautomator2 device."""
    try:
        import uiautomator2 as u2
    except ImportError:
        raise RuntimeError("uiautomator2 not installed: pip install uiautomator2")
    if not VMOS_ADB:
        raise RuntimeError(
            "VMOS_ADB not set. Example: VMOS_ADB=1.2.3.4:5555\n"
            "Get it from VMOS Cloud → Open Cloud Phone → Local Debugging"
        )
    d = u2.connect(VMOS_ADB)
    d.implicitly_wait(10)
    return d


def _scroll_to_top(d) -> None:
    """Scroll up until the feed top — makes 'Добавить' button appear."""
    for _ in range(3):
        d.swipe_ext("up", scale=0.8)
        d.sleep(0.8)


def _tap(d, *text_variants, timeout: int = 8) -> bool:
    """Try each text variant; return True if found and tapped."""
    for text in text_variants:
        el = d(text=text)
        if el.wait(timeout=timeout):
            el.click()
            return True
        el = d(textContains=text[:6])
        if el.exists:
            el.click()
            return True
    return False


def _input_text(d, text: str) -> None:
    """Find the post editor and type text."""
    candidates = [
        d(className="android.widget.EditText"),
        d(className="android.widget.MultiAutoCompleteTextView"),
        d(focused=True),
        d(textContains="Напишите"),
        d(textContains="Текст"),
        d(textContains="Что у вас"),
    ]
    for el in candidates:
        if el.exists:
            el.click()
            d.sleep(0.4)
            el.clear_text()
            el.set_text(text)
            log.info("TenChat VMOS: текст введён")
            return

    # Fallback: tap middle of screen and type
    log.warning("TenChat VMOS: поле ввода не найдено, используем send_keys")
    d.click(0.5, 0.4)
    d.sleep(0.5)
    d.send_keys(text)


def _push_and_attach_images(d, image_paths: list) -> None:
    """Push local images to device via ADB and attach them in TenChat."""
    remote_paths = []
    for i, local_path in enumerate(image_paths[:9]):
        remote = f"/sdcard/Download/tc_post_{i}.jpg"
        result = subprocess.run(
            ["adb", "-s", VMOS_ADB, "push", local_path, remote],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            remote_paths.append(remote)
            log.info(f"TenChat VMOS: фото {i+1} загружено → {remote}")
        else:
            log.warning(f"TenChat VMOS: не удалось загрузить {local_path}: {result.stderr}")

    if not remote_paths:
        return

    # Look for image attachment button
    attached = False
    for desc in ["Прикрепить", "photo", "image", "галерея", "Фото"]:
        el = d(descriptionContains=desc)
        if not el.exists:
            el = d(textContains=desc)
        if el.exists:
            el.click()
            d.sleep(2)
            attached = True
            break

    if not attached:
        # Try generic image button in toolbar area
        btns = d(className="android.widget.ImageButton")
        if btns.count > 0:
            btns[0].click()
            d.sleep(2)

    # Select images in gallery picker
    for i in range(len(remote_paths)):
        img = d(className="android.widget.ImageView").nth(i)
        if img.exists:
            img.long_click() if i == 0 else img.click()
            d.sleep(0.3)

    # Confirm selection
    for confirm in ["Готово", "OK", "Выбрать", "Применить", "Добавить"]:
        if _tap(d, confirm, timeout=3):
            d.sleep(2)
            break


def _post_sync(text: str, image_paths: list) -> dict:
    """Synchronous posting via uiautomator2. Called from async wrapper."""
    try:
        d = _device()
    except RuntimeError as e:
        return {"status": "error", "error": str(e)}

    try:
        # Launch TenChat
        log.info("TenChat VMOS: запуск приложения")
        d.app_start(TENCHAT_PKG, wait=True)
        d.sleep(4)

        # Scroll up to reveal "Добавить" button
        log.info("TenChat VMOS: прокрутка вверх → ожидание кнопки «Добавить»")
        _scroll_to_top(d)
        d.sleep(1)

        # If still not visible after scroll, try scrollable widget
        if not d(text=_BTN_ADD).exists:
            try:
                d(scrollable=True).scroll.toBeginning(max_swipes=5)
                d.sleep(1)
            except Exception:
                pass

        if not d(text=_BTN_ADD).wait(timeout=6):
            d.screenshot(_SCREENSHOT_PATH)
            log.error(f"TenChat VMOS: кнопка «{_BTN_ADD}» не найдена")
            return {
                "status": "error",
                "error": f"Button '{_BTN_ADD}' not found. Screenshot: {_SCREENSHOT_PATH}",
            }

        d(text=_BTN_ADD).click()
        d.sleep(1.5)

        # "Создать запись" in bottom sheet
        if not _tap(d, _BTN_CREATE, "запись", timeout=5):
            d.screenshot(_SCREENSHOT_PATH)
            log.error(f"TenChat VMOS: пункт «{_BTN_CREATE}» не найден")
            return {
                "status": "error",
                "error": f"Menu item '{_BTN_CREATE}' not found. Screenshot: {_SCREENSHOT_PATH}",
            }
        d.sleep(2)

        # Attach images if any (before text so layout doesn't shift)
        if image_paths:
            _push_and_attach_images(d, image_paths)

        # Enter post text
        _input_text(d, text)
        d.sleep(1)

        # Publish
        if not _tap(d, _BTN_PUBLISH, "Опубл", timeout=8):
            d.screenshot(_SCREENSHOT_PATH)
            log.error(f"TenChat VMOS: кнопка «{_BTN_PUBLISH}» не найдена")
            return {
                "status": "error",
                "error": f"Publish button not found. Screenshot: {_SCREENSHOT_PATH}",
            }

        d.sleep(4)
        log.info("TenChat VMOS: пост опубликован ✅")
        return {"status": "ok", "platform": "tenchat", "method": "vmos"}

    except Exception as e:
        log.exception(f"TenChat VMOS: ошибка — {e}")
        try:
            d.screenshot(_SCREENSHOT_PATH)
        except Exception:
            pass
        return {"status": "error", "error": str(e)}


# ─── Публичные async-функции (вызываются из main.py) ─────────────────────────

async def post_text_tenchat_vmos(text: str, title: str = "") -> dict:
    full = f"{title}\n\n{text}" if title else text
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _post_sync, full, [])


async def post_photo_tenchat_vmos(
    image_paths: List[Union[str, bytes]], caption: str = "", title: str = ""
) -> dict:
    tmp_files: list[str] = []
    real_paths: list[str] = []
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

        full = f"{title}\n\n{caption}" if title else caption
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _post_sync, full, real_paths)
    finally:
        for p in tmp_files:
            try:
                os.unlink(p)
            except Exception:
                pass


async def post_video_tenchat_vmos(video_bytes: bytes, caption: str = "", title: str = "") -> dict:
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
        f.write(video_bytes)
        tmp_path = f.name
    try:
        full = f"{title}\n\n{caption}" if title else caption
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _post_sync, full, [tmp_path])
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
