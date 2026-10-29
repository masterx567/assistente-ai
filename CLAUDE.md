# AssistenteAI

Bot Telegram personale (Daniele), Vercel serverless, risponde solo a `TELEGRAM_CHAT_ID`.

## Entry point
- `api/index.py` — webhook + tick cron
- `router.py` — routing messaggi
- `agents/` — budget, calendar, news, reminders, pending, errors

## Spec completa
Leggi `agents/SPEC.md` per: DB IDs, routing order, flussi conferma, bug noti, env vars, cron windows.

## Pipeline degli aggiornamenti
Idee ogni 2 settimane → ✅ Daniele → Claude sviluppa su `idea-N` → prova sull'anteprima → 🚀 Daniele → rilascio con tag vX.Y.Z.
Schema: `.claude/context/pipeline-aggiornamenti.md`. Repo pubblico: mai dati personali in Issue, PR, log.
