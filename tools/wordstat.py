import os
import httpx

WORDSTAT_TOKEN = os.getenv("YANDEX_WORDSTAT_TOKEN")


async def get_keywords(phrase: str) -> list:
    async with httpx.AsyncClient() as client:
        r = await client.post(
            "https://api.wordstat.yandex.net/v1/topRequests",
            headers={
                "Authorization": f"Bearer {WORDSTAT_TOKEN}",
                "Content-Type": "application/json"
            },
            json={
                "phrase": phrase,
                "regions": [225],
                "numPhrases": 500
            },
            timeout=20
        )
        data = r.json()
        return data.get("topRequests", [])[:50]