import os
import asyncio
import tempfile
import logging
from pathlib import Path
from datetime import datetime

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from aiogram.filters import Command
from aiogram.fsm.storage.memory import MemoryStorage
from openai import AsyncOpenAI
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

from .memory import (
    load_memory,
    save_memory,
    init_memory,
    update_state,
    add_task,
    complete_task,
    log_day,
    get_profile_summary,
)
from .prompts import get_system_prompt, MORNING_CHECKIN, EVENING_REVIEW, CONTENT_IDEAS_PROMPT, WEEK_PLAN_PROMPT
from .trends import get_niche_trends, get_content_trends

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BALI_TZ = pytz.timezone("Asia/Makassar")

_bot: Bot = None
_openai: AsyncOpenAI = None
_conversation: dict[int, list] = {}


def _get_allowed_id() -> int:
    val = os.getenv("JARVIS_USER_ID", "0")
    try:
        return int(val)
    except ValueError:
        return 0


def _get_history(user_id: int) -> list:
    if user_id not in _conversation:
        _conversation[user_id] = []
    return _conversation[user_id]


def _add_to_history(user_id: int, role: str, content: str):
    history = _get_history(user_id)
    history.append({"role": role, "content": content})
    if len(history) > 30:
        _conversation[user_id] = history[-30:]


async def _chat(user_id: int, user_message: str) -> str:
    _add_to_history(user_id, "user", user_message)
    messages = [{"role": "system", "content": get_system_prompt()}] + _get_history(user_id)
    try:
        resp = await _openai.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            max_tokens=1200,
            temperature=0.7,
        )
        reply = resp.choices[0].message.content
        _add_to_history(user_id, "assistant", reply)
        return reply
    except Exception as e:
        logger.error(f"OpenAI error: {e}")
        return f"Ошибка OpenAI: {e}"


async def _transcribe(voice_file_id: str) -> str:
    file = await _bot.get_file(voice_file_id)
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
        await _bot.download_file(file.file_path, tmp.name)
        tmp_path = tmp.name
    try:
        with open(tmp_path, "rb") as f:
            transcript = await _openai.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                language="ru",
            )
        return transcript.text
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def _split_message(text: str, limit: int = 4000) -> list[str]:
    if len(text) <= limit:
        return [text]
    parts = []
    while text:
        parts.append(text[:limit])
        text = text[limit:]
    return parts


async def _send(message: Message, text: str):
    for part in _split_message(text):
        await message.answer(part)


# ── keyboards ──────────────────────────────────────────────────────────────

def kb_main() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="☀️ Утро", callback_data="morning"),
            InlineKeyboardButton(text="🌙 Вечер", callback_data="evening"),
        ],
        [
            InlineKeyboardButton(text="🎯 Цели", callback_data="goals"),
            InlineKeyboardButton(text="✅ Задачи", callback_data="tasks"),
        ],
        [
            InlineKeyboardButton(text="📈 Тренды", callback_data="trends"),
            InlineKeyboardButton(text="💡 Контент", callback_data="content"),
        ],
        [
            InlineKeyboardButton(text="📅 План недели", callback_data="week_plan"),
            InlineKeyboardButton(text="🧠 Профиль", callback_data="profile"),
        ],
        [
            InlineKeyboardButton(text="➕ Добавить задачу", callback_data="add_task"),
            InlineKeyboardButton(text="🗑 Закрыть задачу", callback_data="done_task"),
        ],
    ])


def kb_back() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Меню", callback_data="menu")]
    ])


# ── command handlers ────────────────────────────────────────────────────────

router = Router()


def _is_allowed(user_id: int) -> bool:
    allowed = _get_allowed_id()
    return allowed == 0 or user_id == allowed


@router.message(Command("start"))
async def cmd_start(message: Message):
    if not _is_allowed(message.from_user.id):
        return
    init_memory()
    await message.answer(
        "Jarvis активирован. Твой персональный оператор онлайн.\n\nЧто делаем?",
        reply_markup=kb_main(),
    )


@router.message(Command("menu"))
async def cmd_menu(message: Message):
    if not _is_allowed(message.from_user.id):
        return
    await message.answer("Главное меню:", reply_markup=kb_main())


# ── callback handlers ───────────────────────────────────────────────────────

@router.callback_query(F.data == "menu")
async def cb_menu(call: CallbackQuery):
    if not _is_allowed(call.from_user.id):
        return
    await call.message.edit_text("Главное меню:", reply_markup=kb_main())
    await call.answer()


@router.callback_query(F.data == "morning")
async def cb_morning(call: CallbackQuery):
    if not _is_allowed(call.from_user.id):
        return
    await call.message.edit_text(MORNING_CHECKIN, reply_markup=kb_back())
    await call.answer()


@router.callback_query(F.data == "evening")
async def cb_evening(call: CallbackQuery):
    if not _is_allowed(call.from_user.id):
        return
    await call.message.edit_text(EVENING_REVIEW, reply_markup=kb_back())
    await call.answer()


@router.callback_query(F.data == "goals")
async def cb_goals(call: CallbackQuery):
    if not _is_allowed(call.from_user.id):
        return
    await call.answer("Загружаю...")
    memory = load_memory()
    g = memory["goals"]
    e = memory["execution"]
    weekly = "\n".join(f"  • {t}" for t in g.get("weekly", [])) or "  не заданы"
    quarterly = "\n".join(f"  • {t}" for t in g.get("quarterly", [])) or "  не заданы"
    priorities = "\n".join(f"  • {t}" for t in e.get("priorities", [])) or "  не заданы"
    text = (
        f"🎯 Цели\n\n"
        f"Главная: {g['primary']}\n\n"
        f"Выход в ноль: {g['monthly_breakeven_rub']:,}₽/мес\n"
        f"Комфорт: {g['monthly_comfort_rub']:,}₽/мес\n\n"
        f"Контекст: {g['family_context']}\n\n"
        f"Приоритеты сейчас:\n{priorities}\n\n"
        f"На неделю:\n{weekly}\n\n"
        f"На квартал:\n{quarterly}"
    )
    await call.message.edit_text(text, reply_markup=kb_back())


@router.callback_query(F.data == "tasks")
async def cb_tasks(call: CallbackQuery):
    if not _is_allowed(call.from_user.id):
        return
    await call.answer("Загружаю...")
    memory = load_memory()
    ex = memory["execution"]
    current = ex.get("current_tasks", [])
    pending = ex.get("pending_tasks", [])
    c_text = "\n".join(f"  • {t}" for t in current) if current else "  — пусто"
    p_text = "\n".join(f"  • {t}" for t in pending) if pending else "  — пусто"
    text = f"✅ Задачи\n\nТекущие:\n{c_text}\n\nЗависшие:\n{p_text}"
    await call.message.edit_text(text, reply_markup=kb_back())


@router.callback_query(F.data == "trends")
async def cb_trends(call: CallbackQuery):
    if not _is_allowed(call.from_user.id):
        return
    await call.answer("Ищу тренды...")
    await call.message.edit_text("📈 Ищу тренды в нише... (10-20 секунд)")
    trends_raw = get_niche_trends()
    summary = await _chat(
        call.from_user.id,
        f"Вот данные по трендам:\n\n{trends_raw}\n\n"
        f"Дай краткую выжимку: что актуально прямо сейчас, как это использовать в офферах и контенте Славы."
    )
    for part in _split_message(f"📈 Тренды в нише\n\n{summary}"):
        await call.message.answer(part)
    await call.message.answer("Главное меню:", reply_markup=kb_main())


@router.callback_query(F.data == "content")
async def cb_content(call: CallbackQuery):
    if not _is_allowed(call.from_user.id):
        return
    await call.answer("Генерирую идеи...")
    await call.message.edit_text("💡 Генерирую идеи для контента...")
    result = await _chat(call.from_user.id, CONTENT_IDEAS_PROMPT)
    for part in _split_message(f"💡 Идеи для контента\n\n{result}"):
        await call.message.answer(part)
    await call.message.answer("Главное меню:", reply_markup=kb_main())


@router.callback_query(F.data == "week_plan")
async def cb_week_plan(call: CallbackQuery):
    if not _is_allowed(call.from_user.id):
        return
    await call.answer("Составляю план...")
    await call.message.edit_text("📅 Составляю план на неделю...")
    result = await _chat(call.from_user.id, WEEK_PLAN_PROMPT)
    for part in _split_message(f"📅 План на неделю\n\n{result}"):
        await call.message.answer(part)
    await call.message.answer("Главное меню:", reply_markup=kb_main())


@router.callback_query(F.data == "profile")
async def cb_profile(call: CallbackQuery):
    if not _is_allowed(call.from_user.id):
        return
    await call.answer("Загружаю...")
    memory = load_memory()
    identity = memory["identity"]
    patterns = memory["patterns"]
    state = memory["state"]
    text = (
        f"🧠 Профиль\n\n"
        f"Имя: {identity['name']}, {identity['age']} лет\n"
        f"Локация: {identity['location']}\n\n"
        f"Навыки: {', '.join(identity['skills'])}\n"
        f"Инструменты: {', '.join(identity['tools'])}\n\n"
        f"Текущее состояние:\n"
        f"  Стресс: {state.get('stress') or '—'}/10\n"
        f"  Энергия: {state.get('energy') or '—'}/10\n"
        f"  Настроение: {state.get('mood') or '—'}/10\n\n"
        f"Паттерны-блокеры:\n" +
        "\n".join(f"  ⚠️ {b}" for b in patterns.get("blockers", []))
    )
    await call.message.edit_text(text, reply_markup=kb_back())


@router.callback_query(F.data == "add_task")
async def cb_add_task(call: CallbackQuery):
    if not _is_allowed(call.from_user.id):
        return
    await call.message.edit_text(
        "Напиши задачу текстом — я добавлю её в список.\n\nФормат: /task Текст задачи",
        reply_markup=kb_back()
    )
    await call.answer()


@router.callback_query(F.data == "done_task")
async def cb_done_task(call: CallbackQuery):
    if not _is_allowed(call.from_user.id):
        return
    await call.message.edit_text(
        "Напиши какую задачу закрыть.\n\nФормат: /done Текст задачи",
        reply_markup=kb_back()
    )
    await call.answer()


# ── task commands ────────────────────────────────────────────────────────────

@router.message(Command("task"))
async def cmd_task(message: Message):
    if not _is_allowed(message.from_user.id):
        return
    task_text = message.text.removeprefix("/task").strip()
    if not task_text:
        await message.answer("Укажи задачу: /task Текст задачи")
        return
    add_task(task_text, "current")
    await message.answer(f"✅ Задача добавлена:\n{task_text}", reply_markup=kb_back())


@router.message(Command("done"))
async def cmd_done(message: Message):
    if not _is_allowed(message.from_user.id):
        return
    task_text = message.text.removeprefix("/done").strip()
    if not task_text:
        await message.answer("Укажи задачу: /done Текст задачи")
        return
    complete_task(task_text)
    await message.answer(f"✔️ Задача закрыта:\n{task_text}", reply_markup=kb_back())


# ── voice ────────────────────────────────────────────────────────────────────

@router.message(F.voice)
async def handle_voice(message: Message):
    if not _is_allowed(message.from_user.id):
        return
    processing_msg = await message.answer("🎙 Слушаю...")
    try:
        text = await _transcribe(message.voice.file_id)
        await processing_msg.edit_text(f"🎙 _{text}_", parse_mode="Markdown")
        response = await _chat(message.from_user.id, text)
        await _send(message, response)
    except Exception as e:
        logger.error(f"Voice error: {e}")
        await processing_msg.edit_text(f"Ошибка обработки голоса: {e}")


# ── text ─────────────────────────────────────────────────────────────────────

@router.message(F.text & ~F.text.startswith("/"))
async def handle_text(message: Message):
    if not _is_allowed(message.from_user.id):
        return
    response = await _chat(message.from_user.id, message.text)
    await _send(message, response)


# ── scheduler ────────────────────────────────────────────────────────────────

async def _send_morning():
    uid = _get_allowed_id()
    if uid:
        await _bot.send_message(uid, MORNING_CHECKIN, reply_markup=kb_back())


async def _send_evening():
    uid = _get_allowed_id()
    if uid:
        await _bot.send_message(uid, EVENING_REVIEW, reply_markup=kb_back())


# ── entry point ───────────────────────────────────────────────────────────────

async def run():
    global _bot, _openai

    token = os.getenv("JARVIS_TELEGRAM_TOKEN")
    openai_key = os.getenv("OPENAI_API_KEY")

    if not token:
        raise ValueError("JARVIS_TELEGRAM_TOKEN не задан в .env")
    if not openai_key:
        raise ValueError("OPENAI_API_KEY не задан в .env")

    _bot = Bot(token=token)
    _openai = AsyncOpenAI(api_key=openai_key)

    init_memory()

    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    scheduler = AsyncIOScheduler(timezone=BALI_TZ)
    scheduler.add_job(_send_morning, CronTrigger(hour=8, minute=0, timezone=BALI_TZ))
    scheduler.add_job(_send_evening, CronTrigger(hour=21, minute=0, timezone=BALI_TZ))
    scheduler.start()

    logger.info("Jarvis запущен")
    await dp.start_polling(_bot)
