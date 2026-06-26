# AssistenteAI — Telegram Bot Personale

Bot Telegram personale di Daniele, deployato su Vercel (free tier). Risponde solo al suo `TELEGRAM_CHAT_ID`.

## Stack

- **Runtime**: Vercel serverless (Flask WSGI via `api/index.py`), timeout 10s
- **LLM**: Groq (`llama-3.3-70b-versatile`, `whisper-large-v3-turbo` per vocali)
- **DB**: Notion REST API
- **Calendario**: Google Calendar API (OAuth2 refresh token)
- **Meteo**: wttr.in JSON format (`j1`)
- **Notizie**: Google News RSS + ANSA feed

## Struttura file

```
api/index.py       — Flask app, webhook Telegram, tick cron, send_telegram
router.py          — routing messaggi → handler giusto
agents/
  budget.py        — transazioni Notion, categorie, budget alert, confronto mese
  calendar.py      — CRUD eventi Google Calendar
  news.py          — briefing mattutino (meteo + agenda + notizie + budget)
  reminders.py     — promemoria Notion DB
  pending.py       — stato temporaneo per flusso conferma (usa stesso DB Reminders)
```

## Notion Database IDs

| DB | ID env / hardcoded |
|---|---|
| Transactions | `NOTION_DB_TRANSACTIONS` (env) |
| Categories | `NOTION_DB_CATEGORIES` (env) |
| MerchantMap | `c82a1f2a-a1dc-421b-aeb8-e0fc4e413354` |
| Reminders + Pending | `38a9d2a5-23ac-8158-badb-f41c332b13e4` |

## Cron

**Un solo job attivo** su cron-job.org: `GET /api/tick` ogni 5 minuti.

Il tick gestisce:
- Briefing mattutino: `h==9 and 0<=m<=4`
- Budget serale: `h==20 and 0<=m<=4`
- Notifica inizio mese: `day==1 and h==9 and 0<=m<=4`
- Riepilogo settimanale: domenica 20:00
- Riepilogo mensile: ultimo giorno 20:00
- Reminder calendario Google: day_before (20:00), 2h prima, 1h prima
- Promemoria Notion: `remind_at <= now and sent=False` (salta entry `PENDING:`)

## Flusso conferma transazioni (stateful via Notion)

1. "crea transazione 1€ temu" → Groq estrae dati → lookup MerchantMap → salva `PENDING:add_tx:{json}` in Reminders DB → mostra conferma
2. "sì" → `handle_confirm()` → legge pending → chiama `add_transaction(merchant, amount, date, cat_id)` → se merchant non era in MerchantMap offre di salvarlo
3. "no" → `handle_cancel()` → mostra bottoni inline categoria (callback `sc:{index}`) → pending NON cancellato
4. Click bottone → `handle_category_callback(index)` → ricarica categorie → aggiorna pending → nuova conferma

**IMPORTANTE**: `get_pending()` usa filtro senza `"and"` (singolo elemento). Entries `PENDING:` vengono saltate da `get_pending_reminders()` per non mandarle come reminder.

## Messaggi vocali

Webhook riceve `message.voice` → scarica da Telegram → trascrive con Groq Whisper → mostra trascrizione in corsivo → passa testo al router.

## Routing (router.py — ordine importante)

1. "sì/no/confermo" → `handle_confirm` / `handle_cancel`
2. "elimina transazione/spesa" → `handle_delete_transaction`
3. "crea transazione/ho speso/ho pagato/aggiungi spesa" → `handle_add_transaction`
4. "ricordami/promemoria" → `handle_reminder`
5. "prossimi impegni/agenda oggi" → `get_today_events`
6. "ultime spese/ultime transazioni" → `get_recent_transactions(10)`
7. "confronto mese/mese scorso" → `get_monthly_comparison`
8. "spes/budget/quanto/soldi" → `get_monthly_spending` + `get_budget_alerts` + Groq
9. "aggiungi/crea/elimina/modifica" (senza "transazione") → `handle_calendar_action`
10. "quando ho/cerca event" → `search_events`
11. "impegn/calendar/agenda" → `get_events(days_ahead=7)`
12. "notizi/news/briefing" → `get_morning_briefing`
13. fallback → `ask_groq`

## Errori noti e fix applicati

- `*` nei nomi merchant rompeva Markdown → `send_telegram` retry senza `parse_mode`
- callback_data Telegram max 64 byte → bottoni categoria usano indice numerico `sc:{i}`
- `get_pending()` non usava `"and"` con un solo filtro → bug silenzioso Notion API
- Finestre tick 6 min con cron 5 min → 2 notifiche → ridotto a 4 min
- Groq estraeva "elimina transazione" come parte del merchant → prompt fix con esempi

## Variabili d'ambiente necessarie

```
TELEGRAM_TOKEN
TELEGRAM_CHAT_ID
NOTION_TOKEN
NOTION_DB_TRANSACTIONS
NOTION_DB_CATEGORIES
GROQ_API_KEY
GOOGLE_CLIENT_ID
GOOGLE_CLIENT_SECRET
GOOGLE_REFRESH_TOKEN
```
