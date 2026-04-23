"""
Lightweight RAG — OpenAI embeddings stored as JSON.
No extra vector DB needed. Works locally and on Railway with a /data volume.
"""
import json
import math
import os
from datetime import datetime
from pathlib import Path

from openai import AsyncOpenAI

_DATA_DIR = Path("/data") if Path("/data").exists() else Path(__file__).parent.parent
RAG_FILE = Path(os.getenv("RAG_FILE", str(_DATA_DIR / "jarvis_rag.json")))

EMBEDDING_MODEL = "text-embedding-3-small"
MIN_SIMILARITY = 0.35
MIN_TEXT_LEN = 25  # Don't embed very short messages


# ── storage ────────────────────────────────────────────────────────────────

def _load() -> list[dict]:
    if RAG_FILE.exists():
        with open(RAG_FILE, encoding="utf-8") as f:
            try:
                return json.load(f)
            except (json.JSONDecodeError, ValueError):
                return []
    return []


def _save(entries: list[dict]):
    RAG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(RAG_FILE, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)


# ── math ───────────────────────────────────────────────────────────────────

def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x ** 2 for x in a))
    nb = math.sqrt(sum(x ** 2 for x in b))
    return dot / (na * nb) if na and nb else 0.0


# ── public API ─────────────────────────────────────────────────────────────

async def save_entry(
    client: AsyncOpenAI,
    text: str,
    source: str = "conversation",
    tags: list[str] | None = None,
) -> bool:
    if len(text.strip()) < MIN_TEXT_LEN:
        return False
    try:
        resp = await client.embeddings.create(model=EMBEDDING_MODEL, input=text)
        embedding = resp.data[0].embedding
    except Exception:
        return False

    entries = _load()
    entries.append({
        "id": f"{source}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}",
        "text": text,
        "source": source,
        "tags": tags or [],
        "date": datetime.now().strftime("%Y-%m-%d"),
        "timestamp": datetime.now().isoformat(),
        "embedding": embedding,
    })
    _save(entries)
    return True


async def search(
    client: AsyncOpenAI,
    query: str,
    top_k: int = 5,
    source: str | None = None,
) -> list[dict]:
    entries = _load()
    if not entries:
        return []

    pool = [e for e in entries if source is None or e.get("source") == source]
    if not pool:
        return []

    try:
        resp = await client.embeddings.create(model=EMBEDDING_MODEL, input=query)
        q_vec = resp.data[0].embedding
    except Exception:
        return []

    scored = sorted(
        ((e, _cosine(q_vec, e["embedding"])) for e in pool),
        key=lambda x: x[1],
        reverse=True,
    )

    return [
        {"text": e["text"], "source": e["source"], "date": e["date"],
         "tags": e.get("tags", []), "score": round(s, 3)}
        for e, s in scored[:top_k]
        if s >= MIN_SIMILARITY
    ]


def get_ideas(limit: int = 30) -> list[dict]:
    entries = _load()
    ideas = [e for e in entries if e.get("source") == "idea"]
    ideas.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    return [
        {"text": e["text"], "date": e["date"], "tags": e.get("tags", [])}
        for e in ideas[:limit]
    ]


def format_context(items: list[dict], max_chars: int = 1500) -> str:
    if not items:
        return ""
    lines = ["[Из базы памяти — релевантный контекст:]"]
    used = 0
    for item in items:
        snippet = f"[{item['date']}] {item['text'][:300]}"
        if used + len(snippet) > max_chars:
            break
        lines.append(f"• {snippet}")
        used += len(snippet)
    return "\n".join(lines)
