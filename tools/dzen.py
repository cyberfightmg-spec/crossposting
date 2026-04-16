import os

DZEN_CLIENT_ID = os.getenv("DZEN_CLIENT_ID")
DZEN_CLIENT_SECRET = os.getenv("DZEN_CLIENT_SECRET")


async def post_dzen(content: str) -> dict:
    """Publish content to Yandex Dzen."""
    return {"status": "not_implemented", "message": "Dzen API requires OAuth"}