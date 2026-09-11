# Telegram Order Forwarder

Userbot (Telethon) that copies bot order messages from one Telegram group to another as normal user messages. Telegram Bot API bots cannot see messages sent by other bots, so an order bot's posts are invisible to trigger bots. This forwarder bridges that gap.

## How it works

1. A user account session listens for new messages in the source group.
2. Messages sent by a bot account and containing the order keyword are re-sent into the target group as plain user messages.
3. Downstream automation (n8n Telegram Trigger, etc.) picks up the copied messages and processes them normally.

## Files

- `listener.py` - the service, reads all config from environment variables
- `gen_session.py` - one-time session string generator, run on a PC
- `requirements.txt` - telethon and python-dotenv
- `Dockerfile` - container image for Coolify or any Docker host
- `.env.example` - template, copy to `.env` and fill in real values

## Environment variables

- `API_ID` and `API_HASH` from my.telegram.org
- `SESSION_STRING` from `gen_session.py` output
- `SOURCE_GROUP_ID` group to listen on
- `TARGET_GROUP_ID` group to copy orders into
- `WABOT_USERNAME` optional, without @. Empty means accept any bot sender.
- `KEYWORD` optional, defaults to `total payment`
- `STATE_FILE` optional, defaults to `state.json`

## Setup

1. `pip install -r requirements.txt`
2. `python gen_session.py`, enter the spare account number and OTP code
3. Copy `.env.example` to `.env` and fill in all values
4. Test locally with `python listener.py`
5. Deploy with Docker, set the same values as container environment variables. No secrets are stored in this repo.

## Notes

- Listens live. Messages missed while the service is down are caught up on start from the state file, up to 50 messages back.
- Human messages are never copied by design.
