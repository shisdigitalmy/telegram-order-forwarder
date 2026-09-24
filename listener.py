"""Ayra Aris order listener v4.

Forward Wabot order text from the private source group to the n8n target group.
For Online Transfer orders, preserve the next JPEG/PNG/PDF receipt as a reply
to the forwarded order message so downstream automation can correlate it by
Telegram message ID without using customer data.
"""

import asyncio
import json
import logging
import os
import tempfile
import time
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.sessions import StringSession

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("ayraaris-listener")

API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
SESSION = os.environ["SESSION_STRING"]
SOURCE_GROUP_ID = int(os.environ["SOURCE_GROUP_ID"])
TARGET_GROUP_ID = int(os.environ["TARGET_GROUP_ID"])
WABOT_USERNAME = os.environ.get("WABOT_USERNAME", "").strip().lower().lstrip("@")
STATE_FILE = Path(os.environ.get("STATE_FILE", "state.json"))
RECEIPT_TTL_SECONDS = int(os.environ.get("RECEIPT_TTL_SECONDS", "7200"))
KEYWORD = "total payment"
ALLOWED_DOCUMENT_MIMES = {"application/pdf", "image/jpeg", "image/png"}


def load_state():
    try:
        raw = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return {
            "last_id": int(raw.get("last_id", 0)),
            "pending_transfers": list(raw.get("pending_transfers", [])),
        }
    except Exception:
        return {"last_id": 0, "pending_transfers": []}


def save_state(state):
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_FILE.with_suffix(STATE_FILE.suffix + ".tmp")
        tmp.write_text(json.dumps(state, separators=(",", ":")), encoding="utf-8")
        tmp.replace(STATE_FILE)
    except Exception as exc:
        log.warning("gagal simpan state: %s", exc)


def looks_like_order(text):
    return KEYWORD in (text or "").lower()


def is_online_transfer(text):
    normalized = (text or "").lower()
    return any(term in normalized for term in ("online transfer", "bank transfer", "manual transfer"))


def receipt_kind(message):
    if getattr(message, "photo", None):
        return "image"
    document = getattr(message, "document", None)
    if not document:
        return None
    mime = (getattr(document, "mime_type", "") or "").lower()
    if mime in ALLOWED_DOCUMENT_MIMES:
        return "pdf" if mime == "application/pdf" else "image"
    return None


def prune_pending(state, now=None):
    cutoff = (now or time.time()) - RECEIPT_TTL_SECONDS
    state["pending_transfers"] = [
        item for item in state.get("pending_transfers", [])
        if float(item.get("created_at", 0)) >= cutoff
    ]


async def sender_is_wabot(message):
    if message.out:
        return False
    sender = await message.get_sender()
    if sender is None or not getattr(sender, "bot", False):
        return False
    if WABOT_USERNAME:
        return (getattr(sender, "username", "") or "").lower() == WABOT_USERNAME
    return True


async def forward_order(client, message, state):
    text = message.raw_text or ""
    if not text or not looks_like_order(text):
        return False
    if not await sender_is_wabot(message):
        return False

    sent = await client.send_message(TARGET_GROUP_ID, text)
    if is_online_transfer(text):
        prune_pending(state)
        state["pending_transfers"].append({
            "source_order_id": int(message.id),
            "target_order_id": int(sent.id),
            "created_at": time.time(),
        })
    log.info("copied order msg %s to target msg %s", message.id, sent.id)
    return True


async def forward_receipt(client, message, state):
    kind = receipt_kind(message)
    if not kind or not await sender_is_wabot(message):
        return False

    prune_pending(state)
    pending = state.get("pending_transfers", [])
    if not pending:
        log.info("ignored unpaired receipt msg %s", message.id)
        return False

    order_ref = pending[0]
    with tempfile.TemporaryDirectory(prefix="ayra-receipt-") as temp_dir:
        local_path = await message.download_media(file=temp_dir)
        if not local_path:
            raise RuntimeError(f"receipt download failed for source msg {message.id}")
        await client.send_file(
            TARGET_GROUP_ID,
            local_path,
            reply_to=int(order_ref["target_order_id"]),
            caption=f"Ayra receipt source {order_ref['source_order_id']}",
            force_document=(kind == "pdf"),
        )

    state["pending_transfers"] = pending[1:]
    log.info(
        "copied receipt msg %s as reply to target msg %s",
        message.id,
        order_ref["target_order_id"],
    )
    return True


async def process_message(client, message, state):
    if await forward_order(client, message, state):
        return "order"
    if await forward_receipt(client, message, state):
        return "receipt"
    return "ignored"


async def catch_up(client, state):
    last = int(state.get("last_id", 0))
    if not last:
        log.info("tiada state lama, mula dengar mesej baru saja")
        return
    missed = await client.get_messages(SOURCE_GROUP_ID, min_id=last, limit=100)
    copied = 0
    for message in sorted(missed, key=lambda item: item.id):
        if message.id <= state["last_id"]:
            continue
        try:
            result = await process_message(client, message, state)
            state["last_id"] = int(message.id)
            save_state(state)
            if result != "ignored":
                copied += 1
        except Exception as exc:
            log.warning("catch-up stopped at msg %s: %s", message.id, exc)
            break
    log.info("catch-up siap, %s item dicopy", copied)


async def main():
    state = load_state()
    state_lock = asyncio.Lock()
    async with TelegramClient(StringSession(SESSION), API_ID, API_HASH) as client:
        me = await client.get_me()
        log.info("login sebagai %s", getattr(me, "username", "?"))
        await catch_up(client, state)

        @client.on(events.NewMessage(chats=SOURCE_GROUP_ID))
        async def handler(event):
            async with state_lock:
                message = event.message
                if message.id <= int(state.get("last_id", 0)):
                    return
                try:
                    await process_message(client, message, state)
                    state["last_id"] = int(message.id)
                    save_state(state)
                except Exception as exc:
                    log.warning("handler gagal untuk msg %s: %s", message.id, exc)

        log.info("dengar group %s, hantar ke %s", SOURCE_GROUP_ID, TARGET_GROUP_ID)
        await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
