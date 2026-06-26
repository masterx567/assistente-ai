# AssistenteAI

Bot Telegram personale (Daniele), Vercel serverless, risponde solo a `TELEGRAM_CHAT_ID`.

## Entry point
- `api/index.py` — webhook + tick cron
- `router.py` — routing messaggi
- `agents/` — budget, calendar, news, reminders, pending, errors

## Spec completa
Leggi `agents/SPEC.md` per: DB IDs, routing order, flussi conferma, bug noti, env vars, cron windows.
