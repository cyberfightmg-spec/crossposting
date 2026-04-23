import os
import asyncio
import tempfile
import logging
from pathlib import Path

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from openai import AsyncOpenAI
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

from .memory import load_memory, init_memory, update_state, add_task, complete_task, get_profile_summary
from .prompts import get_system_prompt, MORNING_CHECKIN, EVENING_REVIEW, CONTENT_IDEAS_PROMPT, WEEK_PLAN_PROMPT
from .trends import get_niche_trends
from . import rag

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BALI_TZ = pytz.timezone("Asia/Makassar")

_bot: Bot = None
_openai: AsyncOpenAI = None
_conversation: dict[int, list] = {}


# ── FSM states ────────────────────────────────────────────────────────────

class JarvisState(StatesGroup):
    waiting_idea = State()
    waiting_recall = State()


# ── helpers ───────────────────────────────────────────────────────────────

def _allowed_id() -> int:
    try:
        return int(os.getenv("JARVIS_USER_ID", "0"))
    except ValueError:
        return 0


def _is_allowed(uid: int) -> bool:
    a = _allowed_id()
    return a == 0 or uid == a


def _history(uid: int) -> list:
    if uid not in _conversation:
        _conversation[uid] = []
    return _conversation[uid]


def _push(uid: int, role: str, content: str):
    h = _history(uid)
    h.append({"role": role, "content": content})
    if len(h) > 30:
        _conversation[uid] = h[-30:]


def _split(text: str, limit: int = 4000) -> list[str]:
    return [text[i:i + limit] for i in range(0, len(text), limit)]


async def _send(target, text: str):
    for part in _split(text):
        await target.answer(part)


# ── chat with RAG ─────────────────────────────────────────────────────────

async def _chat(uid: int, user_message: str, auto_save: bool = True) -> str:
    _push(uid, "user", user_message)

    # Retrieve relevant memories
    rag_items = await rag.search(_openai, user_message, top_k=4)
    rag_ctx = rag.format_context(rag_items)

    system = get_system_prompt()
    if rag_ctx:
        system = f"{system}\n\n{rag_ctx}"

    messages = [{"role": "system", "content": system}] + _history(uid)

    try:
        resp = await _openai.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            max_tokens=1200,
            temperature=0.7,
        )
        reply = resp.choices[0].message.content
        _push(uid, "assistant", reply)

        if auto_save and len(user_message.strip()) >= rag.MIN_TEXT_LEN:
            asyncio.create_task(
                rag.save_entry(
                    _openai,
                    f"Слава: {user_message}\nJarvis: {reply}",
                    source="conversation",
                )
            )

        return reply
    except Exception as e:
        logger.error(f"OpenAI error: {e}")
        return f"Ошибка OpenAI: {e}"


async def _transcribe(file_id: str) -> str:
    f = await _bot.get_file(file_id)
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
        await _bot.download_file(f.file_path, tmp.name)
        tmp_path = tmp.name
    try:
        with open(tmp_path, "rb") as audio:
            tr = await _openai.audio.transcriptions.create(
                model="whisper-1", file=audio, language="ru"
            )
        return tr.text
    finally:
        Path(tmp_path).unlink(missing_ok=True)


# ── keyboards ─────────────────────────────────────────────────────────────

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
            InlineKeyboardButton(text="💾 Сохранить идею", callback_data="save_idea"),
            InlineKeyboardButton(text="📚 Мои идеи", callback_data="my_ideas"),
        ],
        [
            InlineKeyboardButton(text="🔍 Найти в памяти", callback_data="recall"),
            InlineKeyboardButton(text="➕ Добавить задачу", callback_data="add_task"),
        ],
    ])


def kb_back() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Меню", callback_data="menu")]
    ])


def kb_cancel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="menu")]
    ])


# ── router ────────────────────────────────────────────────────────────────

router = Router()


# ── commands ──────────────────────────────────────────────────────────────

@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    if not _is_allowed(message.from_user.id):
        return
    await state.clear()
    init_memory()
    await message.answer(
        "Jarvis активирован. Твой персональный оператор онлайн.\n\nЧто делаем?",
        reply_markup=kb_main(),
    )


@router.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext):
    if not _is_allowed(message.from_user.id):
        return
    await state.clear()
    await message.answer("Главное меню:", reply_markup=kb_main())


@router.message(Command("task"))
async def cmd_task(message: Message):
    if not _is_allowed(message.from_user.id):
        return
    text = message.text.removeprefix("/task").strip()
    if not text:
        await message.answer("Формат: /task Текст задачи")
        return
    add_task(text, "current")
    await message.answer(f"✅ Задача добавлена:\n{text}", reply_markup=kb_back())


@router.message(Command("done"))
async def cmd_done(message: Message):
    if not _is_allowed(message.from_user.id):
        return
    text = message.text.removeprefix("/done").strip()
    if not text:
        await message.answer("Формат: /done Текст задачи")
        return
    complete_task(text)
    await message.answer(f"✔️ Задача закрыта:\n{text}", reply_markup=kb_back())


@router.message(Command("idea"))
async def cmd_idea(message: Message):
    if not _is_allowed(message.from_user.id):
        return
    text = message.text.removeprefix("/idea").strip()
    if not text:
        await message.answer("Формат: /idea Текст идеи")
        return
    ok = await rag.save_entry(_openai, text, source="idea")
    if ok:
        await message.answer(f"💾 Идея сохранена в базу:\n_{text}_", parse_mode="Markdown", reply_markup=kb_back())
    else:
        await message.answer("Ошибка сохранения.", reply_markup=kb_back())


@router.message(Command("recall"))
async def cmd_recall(message: Message):
    if not _is_allowed(message.from_user.id):
        return
    query = message.text.removeprefix("/recall").strip()
    if not query:
        await message.answer("Формат: /recall поисковый запрос")
        return
    items = await rag.search(_openai, query, top_k=5)
    if not items:
        await message.answer("Ничего не найдено в памяти.", reply_markup=kb_back())
        return
    lines = [f"🔍 По запросу: *{query}*\n"]
    for i, item in enumerate(items, 1):
        lines.append(f"{i}. [{item['date']}]\n{item['text'][:300]}")
    await message.answer("\n\n".join(lines), parse_mode="Markdown", reply_markup=kb_back())


# ── callbacks ─────────────────────────────────────────────────────────────

@router.callback_query(F.data == "menu")
async def cb_menu(call: CallbackQuery, state: FSMContext):
    if not _is_allowed(call.from_user.id):
        return
    await state.clear()
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
    priorities = "\n".join(f"  • {t}" for t in e.get("priorities", [])) or "  не заданы"
    text = (
        f"🎯 Цели\n\n"
        f"Главная: {g['primary']}\n\n"
        f"Выход в ноль: {g['monthly_breakeven_rub']:,}₽/мес\n"
        f"Комфорт: {g['monthly_comfort_rub']:,}₽/мес\n\n"
        f"Приоритеты:\n{priorities}\n\n"
        f"На неделю:\n{weekly}"
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
    c = "\n".join(f"  • {t}" for t in current) if current else "  — пусто"
    p = "\n".join(f"  • {t}" for t in pending) if pending else "  — пусто"
    await call.message.edit_text(
        f"✅ Задачи\n\nТекущие:\n{c}\n\nЗависшие:\n{p}",
        reply_markup=kb_back()
    )


@router.callback_query(F.data == "trends")
async def cb_trends(call: CallbackQuery):
    if not _is_allowed(call.from_user.id):
        return
    await call.answer("Ищу тренды...")
    await call.message.edit_text("📈 Ищу тренды в нише... подожди 15-20 сек")
    trends_raw = get_niche_trends()
    summary = await _chat(
        call.from_user.id,
        f"Данные по трендам:\n\n{trends_raw}\n\nКраткая выжимка: что актуально, как использовать в офферах и контенте.",
        auto_save=False,
    )
    for part in _split(f"📈 Тренды в нише\n\n{summary}"):
        await call.message.answer(part)
    await call.message.answer("Главное меню:", reply_markup=kb_main())


@router.callback_query(F.data == "content")
async def cb_content(call: CallbackQuery):
    if not _is_allowed(call.from_user.id):
        return
    await call.answer("Генерирую...")
    await call.message.edit_text("💡 Генерирую идеи для контента...")
    result = await _chat(call.from_user.id, CONTENT_IDEAS_PROMPT, auto_save=False)
    for part in _split(f"💡 Идеи для контента\n\n{result}"):
        await call.message.answer(part)
    await call.message.answer("Главное меню:", reply_markup=kb_main())


@router.callback_query(F.data == "week_plan")
async def cb_week_plan(call: CallbackQuery):
    if not _is_allowed(call.from_user.id):
        return
    await call.answer("Составляю план...")
    await call.message.edit_text("📅 Составляю план на неделю...")
    result = await _chat(call.from_user.id, WEEK_PLAN_PROMPT, auto_save=False)
    for part in _split(f"📅 План на неделю\n\n{result}"):
        await call.message.answer(part)
    await call.message.answer("Главное меню:", reply_markup=kb_main())


@router.callback_query(F.data == "profile")
async def cb_profile(call: CallbackQuery):
    if not _is_allowed(call.from_user.id):
        return
    await call.answer("Загружаю...")
    memory = load_memory()
    identity = memory["identity"]
    state = memory["state"]
    patterns = memory["patterns"]
    text = (
        f"🧠 Профиль\n\n"
        f"{identity['name']}, {identity['age']} лет, {identity['location']}\n\n"
        f"Навыки: {', '.join(identity['skills'])}\n\n"
        f"Состояние:\n"
        f"  Стресс: {state.get('stress') or '—'}/10\n"
        f"  Энергия: {state.get('energy') or '—'}/10\n"
        f"  Настроение: {state.get('mood') or '—'}/10\n\n"
        f"Паттерны:\n" + "\n".join(f"  ⚠️ {b}" for b in patterns.get("blockers", []))
    )
    await call.message.edit_text(text, reply_markup=kb_back())


@router.callback_query(F.data == "save_idea")
async def cb_save_idea(call: CallbackQuery, state: FSMContext):
    if not _is_allowed(call.from_user.id):
        return
    await state.set_state(JarvisState.waiting_idea)
    await call.message.edit_text(
        "💾 Напиши идею — я сохраню её в базу.\n\n"
        "Можешь написать текстом или отправить голосовое.",
        reply_markup=kb_cancel(),
    )
    await call.answer()


@router.callback_query(F.data == "my_ideas")
async def cb_my_ideas(call: CallbackQuery):
    if not _is_allowed(call.from_user.id):
        return
    await call.answer("Загружаю...")
    ideas = rag.get_ideas(limit=15)
    if not ideas:
        await call.message.edit_text(
            "📚 Идей пока нет.\n\nНажми 💾 Сохранить идею или используй /idea текст",
            reply_markup=kb_back()
        )
        return
    lines = ["📚 Сохранённые идеи:\n"]
    for i, idea in enumerate(ideas, 1):
        tags = f" [{', '.join(idea['tags'])}]" if idea.get("tags") else ""
        lines.append(f"{i}. [{idea['date']}]{tags}\n{idea['text'][:250]}")
    await call.message.edit_text("\n\n".join(lines), reply_markup=kb_back())


@router.callback_query(F.data == "recall")
async def cb_recall(call: CallbackQuery, state: FSMContext):
    if not _is_allowed(call.from_user.id):
        return
    await state.set_state(JarvisState.waiting_recall)
    await call.message.edit_text(
        "🔍 Что ищем в памяти? Напиши запрос.",
        reply_markup=kb_cancel(),
    )
    await call.answer()


@router.callback_query(F.data == "add_task")
async def cb_add_task(call: CallbackQuery):
    if not _is_allowed(call.from_user.id):
        return
    await call.message.edit_text(
        "Добавить задачу:\n/task Текст задачи",
        reply_markup=kb_back()
    )
    await call.answer()


# ── FSM handlers ──────────────────────────────────────────────────────────

@router.message(JarvisState.waiting_idea, F.voice)
async def fsm_idea_voice(message: Message, state: FSMContext):
    if not _is_allowed(message.from_user.id):
        return
    processing = await message.answer("🎙 Слушаю...")
    text = await _transcribe(message.voice.file_id)
    await processing.edit_text(f"🎙 _{text}_", parse_mode="Markdown")
    await _save_idea_text(message, state, text)


@router.message(JarvisState.waiting_idea, F.text & ~F.text.startswith("/"))
async def fsm_idea_text(message: Message, state: FSMContext):
    if not _is_allowed(message.from_user.id):
        return
    await _save_idea_text(message, state, message.text)


async def _save_idea_text(message: Message, state: FSMContext, text: str):
    await state.clear()
    ok = await rag.save_entry(_openai, text, source="idea")
    if ok:
        await message.answer(
            f"💾 Идея сохранена:\n_{text[:400]}_",
            parse_mode="Markdown",
            reply_markup=kb_main(),
        )
    else:
        await message.answer("Ошибка сохранения.", reply_markup=kb_main())


@router.message(JarvisState.waiting_recall, F.text & ~F.text.startswith("/"))
async def fsm_recall(message: Message, state: FSMContext):
    if not _is_allowed(message.from_user.id):
        return
    await state.clear()
    query = message.text
    items = await rag.search(_openai, query, top_k=5)
    if not items:
        await message.answer("По запросу ничего не найдено.", reply_markup=kb_main())
        return
    lines = [f"🔍 *{query}*\n"]
    for i, item in enumerate(items, 1):
        lines.append(f"{i}. [{item['date']}]\n{item['text'][:350]}")
    await message.answer("\n\n".join(lines), parse_mode="Markdown", reply_markup=kb_main())


# ── voice (normal mode) ───────────────────────────────────────────────────

@router.message(F.voice)
async def handle_voice(message: Message):
    if not _is_allowed(message.from_user.id):
        return
    processing = await message.answer("🎙 Слушаю...")
    try:
        text = await _transcribe(message.voice.file_id)
        await processing.edit_text(f"🎙 _{text}_", parse_mode="Markdown")
        response = await _chat(message.from_user.id, text)
        await _send(message, response)
    except Exception as e:
        logger.error(f"Voice error: {e}")
        await processing.edit_text(f"Ошибка: {e}")


# ── text (normal mode) ────────────────────────────────────────────────────

@router.message(F.text & ~F.text.startswith("/"))
async def handle_text(message: Message):
    if not _is_allowed(message.from_user.id):
        return
    response = await _chat(message.from_user.id, message.text)
    await _send(message, response)


# ── scheduler ─────────────────────────────────────────────────────────────

async def _send_morning():
    uid = _allowed_id()
    if uid:
        await _bot.send_message(uid, MORNING_CHECKIN, reply_markup=kb_back())


async def _send_evening():
    uid = _allowed_id()
    if uid:
        await _bot.send_message(uid, EVENING_REVIEW, reply_markup=kb_back())


# ── entry point ───────────────────────────────────────────────────────────

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
