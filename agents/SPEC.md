# AssistenteAI — Specifica Tecnica

## Stack
- Vercel serverless Flask WSGI, timeout 10s
- Groq: `llama-3.3-70b-versatile` (routing/extraction), `whisper-large-v3-turbo` (vocali/video)
- Notion REST API (DB dati)
- Google Calendar API (OAuth2 refresh token) + iCal read
- wttr.in `j1` format (meteo), Google News RSS + ANSA (notizie)

## File principali
```
api/index.py     webhook Telegram, tick cron, send_telegram, transcribe_voice
router.py        routing msg → handler + prefissi conversazionali stripped
agents/
  budget.py      transazioni, categorie, budget alert, confronto mese, entrate, spese per periodo
  calendar.py    CRUD eventi Google Calendar + search + format (giorni IT)
  news.py        briefing mattutino, meteo IT (weatherCode map), forecast 3gg
  reminders.py   promemoria Notion (salta entry PENDING:)
  pending.py     stato temporaneo conferme (stesso DB Reminders, prefix PENDING:)
  errors.py      log errori su BotErrors DB Notion
  piante.py      reminder irrigazione (fioriera/vaso), mood/streak, meteo Cormano
```

## Notion DB IDs
| DB | ID |
|---|---|
| Transactions | `NOTION_DB_TRANSACTIONS` (env) |
| Categories | `NOTION_DB_CATEGORIES` (env) |
| MerchantMap | `c82a1f2a-a1dc-421b-aeb8-e0fc4e413354` |
| Reminders + Pending | `38a9d2a5-23ac-8158-badb-f41c332b13e4` |
| BotErrors | `38b9d2a5-23ac-81f5-935c-c9b665d4330f` |
| Irrigazione | `41a6389f8060493f80a2976518fd528c` |

## Env vars
```
TELEGRAM_TOKEN  TELEGRAM_CHAT_ID
NOTION_TOKEN  NOTION_DB_TRANSACTIONS  NOTION_DB_CATEGORIES
GROQ_API_KEY
GOOGLE_CLIENT_ID  GOOGLE_CLIENT_SECRET  GOOGLE_REFRESH_TOKEN
GOOGLE_CALENDAR_ICAL_URL
```

## Cron
Un solo job su cron-job.org: `GET /api/tick` ogni 5 min.
Finestre: `0<=m<=4` (4 min max 1 fire per evento).

| Condizione | Azione |
|---|---|
| h==9, 0<=m<=4 | briefing mattutino |
| h==20, 0<=m<=4 | budget serale |
| day==1, h==9 | notifica inizio mese |
| domenica h==20 | riepilogo settimanale |
| ultimo giorno h==20 | riepilogo mensile |
| 20:00 day_before evento | reminder calendario |
| 2h/1h prima evento | reminder calendario |
| remind_at<=now, sent=False | promemoria Notion (salta PENDING:) |
| h==8 o h==20, 0<=m<=4 | reminder irrigazione (se scaduto, meteo-corretto) |

## Routing (ordine CRITICO — non riordinare)
1. confirm kw → `handle_confirm()`
2. cancel kw → `handle_cancel()`
3. entrate kw → `handle_add_income()`
4. del_tx_kw (es. "elimina transazione") → `handle_delete_transaction()`
5. tx_kw (es. "ho speso") OR (verbo+sostantivo transazione) → `handle_add_transaction()`
6. today_kw (es. "agenda oggi") → `get_today_events()`
7. future_kw (es. "prossimo mese") → `get_events(30|14)`
8. reminder_kw → `handle_reminder()`
9. remaining_kw (es. "quanto mi rimane") → `get_remaining_budget()`
10. recent_kw (es. "ultime spese") → `get_recent_transactions` o `get_transactions_by_period`
11. compare_kw (es. "mese scorso") → `get_monthly_comparison()`
12. budget kw (es. "spes/budget/soldi") → spending+alerts+Groq
13. add/del/mod kw calendario → `handle_calendar_action()`
14. search_kw (es. "quando ho") → `search_events(365)`
15. cal_keywords (es. "impegn/agenda") → `get_events(7)`
16. news_kw → `get_morning_briefing()`
17. fallback → `ask_groq()`

## Flusso conferma transazione
1. Groq estrae merchant+amount+date → lookup MerchantMap → `save_pending("add_tx", {...})`
2. "sì" → `handle_confirm()` → `add_transaction(merchant, amount, date, cat_id)` → offre save MerchantMap se cat cambiata
3. "no" → `handle_cancel()` → mostra bottoni inline categoria (`sc:{index}`, max 5 byte) → pending NON cancellato
4. click bottone → `handle_category_callback(index)` → aggiorna pending → nuova conferma

**Flusso entrata**: stesso pattern con `save_pending("add_income", {...})` → `add_income(source, amount, date)`

## Bug noti / fix applicati
- `*` in merchant rompeva Markdown → retry senza `parse_mode`
- callback_data max 64 byte → `sc:{i}` non UUID
- Notion single-filter no `"and"` wrapper → bug silenzioso
- Whisper aggiunge punto finale → `rstrip(".!?,;:")` su text_lower
- "crei/elimini" (congiuntivo) non matchavano keyword → aggiunte forme verbali
- Prefissi conversazionali ("mi dici", "mostrami") strippati UNA VOLTA in cima al router
- `get_pending_reminders()` salta entry con prefix `PENDING:`
- Tick window 4 min (non 6) con cron 5 min → 1 fire max
