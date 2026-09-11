"""Generate a Telethon session string once. Run on a PC."""
import asyncio
import os

from telethon import TelegramClient
from telethon.sessions import StringSession


async def main():
    api_id = int(os.environ.get("API_ID") or input("API_ID: ").strip())
    api_hash = os.environ.get("API_HASH") or input("API_HASH: ").strip()
    phone = os.environ.get("PHONE") or input("PHONE e.g. +60123456789: ").strip()
    async with TelegramClient(StringSession(), api_id, api_hash) as client:
        await client.start(phone=phone)
        print("SESSION_STRING:")
        print(client.session.save())


if __name__ == "__main__":
    asyncio.run(main())
