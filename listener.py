"""Telegram order forwarder - userbot copy bot order messages.

Listen for new messages in SOURCE group, copy ones sent by a bot and
containing the order keyword to TARGET group as normal user messages.
Bot API triggers cannot see messages from other bots, this bridges gap.
"""

import asyncio
import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.sessions import StringSession

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("order-forwarder")

API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
SESSION = os.environ["SESSION_STRING"]
SOURCE_GROUP_ID = int(os.environ["SOURCE_GROUP_ID"])
TARGET_GROUP_ID = int(os.environ["TARGET_GROUP_ID"])
WABOT_USERNAME = os.environ.get("WABOT_USERNAME", "").strip().lower().lstrip("@")
STATE_FILE = Path(os.environ.get("STATE_FILE", "state.json"))
KEYWORD = os.environ.get("KEYWORD", "total payment")


def load_last_id():
    try:
        return int(json.loads(STATE_FILE.read_text(encoding="utf-8")).get("last_id", 0))
    except Exception:
        return 0


def save_last_id(value):
    try:
        STATE_FILE.write_text(json.dumps({"last_id": value}), encoding="utf-8")
    except Exception as exc:
        log.warning("state save failed: %s", exc)


def looks_like_order(text):
    return KEYWORD in (text or "").lower()


async def sender_is_order_bot(message):
    if message.out:
        return False
    sender = await message.get_sender()
    if sender is None or not getattr(sender, "bot", False):
        return False
    if WABOT_USERNAME:
        return (getattr(sender, "username", "") or "").lower() == WABOT_USERNAME
    return True


async def copy_if_order(client, message):
    text = message.raw_text or ""
    if not text or not looks_like_order(text):
        return False
    if not await sender_is_order_bot(message):
        return False
    await client.send_message(TARGET_GROUP_ID, text)
    save_last_id(message.id)
    log.info("copied order msg %s to target group", message.id)
    return True


async def catch_up(client):
    last = load_last_id()
    if not last:
        log.info("no previous state, listening for new messages only")
        return
    missed = await client.get_messages(SOURCE_GROUP_ID, min_id=last, limit=50)
    count = 0
    for message in sorted(missed, key=lambda m: m.id):
        if message.id <= last:
            continue
        try:
            if await copy_if_order(client, message):
                count += 1
            else:
                save_last_id(message.id)
        except Exception as exc:
            log.warning("skip msg %s: %s", message.id, exc)
    log.info("catch-up done, %s orders copied", count)


async def main():
    async with TelegramClient(StringSession(SESSION), API_ID, API_HASH) as client:
        me = await client.get_me()
        log.info("logged in as %s", getattr(me, "username", "?"))
        await catch_up(client)

        @client.on(events.NewMessage(chats=SOURCE_GROUP_ID))
        async def handler(event):
            try:
                await copy_if_order(client, event.message)
            except Exception as exc:
                log.warning("handler failed: %s", exc)

        log.info("listening group %s, forwarding to %s", SOURCE_GROUP_ID, TARGET_GROUP_ID)
        await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
