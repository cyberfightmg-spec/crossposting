import asyncio
from dotenv import load_dotenv
load_dotenv()

from jarvis.bot import run

if __name__ == "__main__":
    asyncio.run(run())
