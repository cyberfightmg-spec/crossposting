from datetime import datetime

try:
    from duckduckgo_search import DDGS
    DDGS_AVAILABLE = True
except ImportError:
    DDGS_AVAILABLE = False


def _search(query: str, max_results: int = 4) -> list[dict]:
    if not DDGS_AVAILABLE:
        return []
    try:
        with DDGS() as ddgs:
            return list(ddgs.text(query, max_results=max_results))
    except Exception:
        return []


def get_niche_trends() -> str:
    month_year = datetime.now().strftime("%m.%Y")
    queries = [
        f"автоматизация бизнеса telegram боты тренды {month_year}",
        f"make.com automation n8n тренды {month_year}",
        f"AI автоматизация для малого бизнеса {month_year}",
    ]

    lines = []
    for query in queries:
        results = _search(query, max_results=3)
        if results:
            lines.append(f"🔍 {query}")
            for r in results:
                title = r.get("title", "")
                body = r.get("body", "")[:180]
                lines.append(f"  • {title}: {body}")
            lines.append("")

    if not lines:
        return "Поиск недоступен — библиотека duckduckgo-search не установлена или нет соединения."

    return "\n".join(lines)


def get_content_trends() -> str:
    month_year = datetime.now().strftime("%m.%Y")
    queries = [
        f"вирусные reels идеи для бизнеса {month_year}",
        f"тренды коротких видео telegram instagram {month_year}",
    ]

    lines = []
    for query in queries:
        results = _search(query, max_results=3)
        if results:
            lines.append(f"🔍 {query}")
            for r in results:
                title = r.get("title", "")
                body = r.get("body", "")[:180]
                lines.append(f"  • {title}: {body}")
            lines.append("")

    return "\n".join(lines) if lines else "Данные недоступны."
