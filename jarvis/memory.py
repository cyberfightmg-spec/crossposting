import json
import os
from pathlib import Path
from datetime import datetime

_DATA_DIR = Path("/data") if Path("/data").exists() else Path(__file__).parent.parent
MEMORY_FILE = Path(os.getenv("MEMORY_FILE", str(_DATA_DIR / "jarvis_memory.json")))

DEFAULT_MEMORY = {
    "identity": {
        "name": "Слава",
        "age": 39,
        "location": "Бали, UTC+8",
        "skills": ["автоматизация", "чат-боты", "AI-визуал", "видеоконтент", "make.com", "вайбкодинг"],
        "tools": ["make.com", "Jetbot", "Leadtech", "aiogram", "OpenAI API"],
        "roles": ["ИП", "специалист по автоматизации и чат-ботам"],
        "strengths": ["автоматизация бизнес-процессов", "продажи на созвонах", "AI-визуал", "вирусный видеоконтент"],
        "limitations": ["сломан ноутбук — работает с телефона", "нет понимания CRM"]
    },
    "goals": {
        "primary": "Погасить долги, получить стабильный доход",
        "monthly_breakeven_rub": 500000,
        "monthly_comfort_rub": 1000000,
        "family_context": "Дети на Бали (школа и сад), падел с женой, спокойно покупать продукты",
        "quarterly": [],
        "weekly": []
    },
    "services": {
        "crossposting_automation": {
            "description": "Настройка автоматического кросспостинга из Telegram",
            "price_rub": 35000,
            "monthly_usd": 30
        },
        "dzen_automation": {
            "description": "Автоматизация написания статей на Яндекс Дзен",
            "price_from_rub": 80000
        },
        "pinterest_automation": {
            "description": "Автоматизация наполнения Pinterest",
            "base_price_rub": 20000,
            "per_extra_board_rub": 7000
        }
    },
    "audiences": {
        "instagram": {
            "followers": 5000,
            "notes": "Пришли с таймлапс-ролика (2.5М просмотров). Идёт отток — нет регулярного контента."
        },
        "telegram": {
            "subscribers": 700,
            "notes": "Раньше получал клиентов через разборы автоматизаций на YouTube"
        }
    },
    "state": {
        "stress": 10,
        "energy": None,
        "mood": None,
        "focus": None,
        "last_updated": None
    },
    "patterns": {
        "blockers": [
            "Уходит в творческую работу (боты, AI, кодинг) вместо монетизации",
            "Распыление на несколько направлений одновременно",
            "Апатия и прокрастинация при стрессе 10/10"
        ],
        "helpers": [],
        "recurring_issues": [
            "Год без стабильного дохода",
            "Занимает деньги на еду у знакомых и родителей",
            "Знает как продавать, но нет входящего потока лидов"
        ]
    },
    "execution": {
        "current_tasks": [],
        "pending_tasks": [],
        "priorities": ["Получить первого платящего клиента на автоматизацию или бота"],
        "reminders": []
    },
    "daily_logs": []
}


def load_memory() -> dict:
    if MEMORY_FILE.exists():
        with open(MEMORY_FILE, encoding="utf-8") as f:
            try:
                data = json.load(f)
                return data if data else DEFAULT_MEMORY.copy()
            except json.JSONDecodeError:
                return DEFAULT_MEMORY.copy()
    return DEFAULT_MEMORY.copy()


def save_memory(memory: dict):
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(memory, f, ensure_ascii=False, indent=2)


def init_memory():
    if not MEMORY_FILE.exists() or MEMORY_FILE.stat().st_size == 0:
        save_memory(DEFAULT_MEMORY.copy())


def update_state(updates: dict):
    memory = load_memory()
    memory["state"].update(updates)
    memory["state"]["last_updated"] = datetime.now().isoformat()
    save_memory(memory)


def add_task(task: str, task_type: str = "current"):
    memory = load_memory()
    key = f"{task_type}_tasks"
    if key in memory["execution"] and task not in memory["execution"][key]:
        memory["execution"][key].append(task)
    save_memory(memory)


def complete_task(task_text: str):
    memory = load_memory()
    for key in ("current_tasks", "pending_tasks"):
        memory["execution"][key] = [
            t for t in memory["execution"][key] if task_text.lower() not in t.lower()
        ]
    save_memory(memory)


def log_day(entry: dict):
    memory = load_memory()
    entry["date"] = datetime.now().strftime("%Y-%m-%d")
    memory["daily_logs"].append(entry)
    memory["daily_logs"] = memory["daily_logs"][-30:]
    save_memory(memory)


def get_profile_summary() -> str:
    memory = load_memory()
    relevant = {
        "identity": memory["identity"],
        "goals": memory["goals"],
        "services": memory["services"],
        "audiences": memory["audiences"],
        "state": memory["state"],
        "patterns": memory["patterns"],
        "execution": memory["execution"],
        "recent_logs": memory["daily_logs"][-3:] if memory["daily_logs"] else []
    }
    return json.dumps(relevant, ensure_ascii=False, indent=2)
