# AssistenteAI — Specifica Tecnica

## Stack
- Vercel serverless Flask WSGI, timeout 10s
- Groq: `llama-3.3-70b-versatile` (routing/extraction), `whisper-large-v3-turbo` (vocali/video)
- Notion REST API (DB dati)
- Google Calendar API (OAuth2 refresh token) + iCal read
- wttr.in `j1` format (meteo), Google News RSS + ANSA (notizie)

## File principali
```
api/index.py     webhook Telegram, tick cron, send_telegram, transcribe_voice, /api/gym-webhook (check-in Shortcuts)
router.py        routing msg → handler + prefissi conversazionali stripped
agents/
  budget.py      transazioni, categorie, budget alert, confronto mese, entrate, spese per periodo
  calendar.py    CRUD eventi Google Calendar + search + format (giorni IT)
  news.py        briefing mattutino, meteo IT (weatherCode map), forecast 3gg
  reminders.py   promemoria Notion (salta entry PENDING:)
  pending.py     stato temporaneo conferme (stesso DB Reminders, prefix PENDING:)
  errors.py      log errori su BotErrors DB Notion
  piante.py      reminder irrigazione (fioriera/vaso), mood/streak, meteo Cormano
  gamification.py  check-in palestra/camminata, xp/livelli/leghe, loot creature, streak settimanale, scudi
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
| GymGame (stato: xp/livello/streak/scudi/creature/badge, riga singola) | `ba636571a56e404e927c2b0197506963` |
| GymCheckins (log check-in) | `fcc6c148fae142a9b142f9c95331d328` |

## Env vars
```
TELEGRAM_TOKEN  TELEGRAM_CHAT_ID
NOTION_TOKEN  NOTION_DB_TRANSACTIONS  NOTION_DB_CATEGORIES
GROQ_API_KEY
GOOGLE_CLIENT_ID  GOOGLE_CLIENT_SECRET  GOOGLE_REFRESH_TOKEN
GOOGLE_CALENDAR_ICAL_URL
GYM_WEBHOOK_SECRET   # POST /api/gym-webhook (check-in automatico da Apple Shortcuts)
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
| domenica h==21, 0<=m<=4 | valuta settimana palestra (target 3 check-in), offre scudo se fallita |
| lunedì h==23, 0<=m<=4 | fallback: applica penalità palestra se scudo non usato entro deadline |
| venerdì h==20, 0<=m<=4 | nudge palestra se sei a 1-2/3 questa settimana |

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

## Flusso gamification palestra
Router: `"stato palestra"` (scheda) controllato PRIMA di `"palestra"`/`"camminata"` (check-in), stesso blocco di `"annaffi"` in cima al router, prima dello strip prefissi conversazionali.

- Check-in (1x/giorno, idempotente via query su GymCheckins): +10xp, roll rarità (60/25/10/4/1% comune/rara/epica/leggendaria/divinità su pool 50 creature), duplicato → +5/+15/+30/+60/+120xp invece della creatura.
- Livelli: progressivo `100+(N-1)*20` xp/livello, leghe a blocchi di 5 livelli (Bronzo→Leggenda). Delevel possibile se l'xp scende sotto la soglia del livello (`_apply_xp_delta` gestisce salita/discesa a cascata).
- Target settimanale 3 check-in, valutato domenica 21:00 (`evaluate_week`): fallito + scudi>0 → bottone `gs:shield` (PenaltyPending=True, non applica subito); non cliccato entro lunedì 23:59 → fallback applica -15xp e azzera streak (`apply_pending_penalty_fallback`); scudi guadagnati +1 ogni 5 livelli, max 3.
- `StreakBrokenRecently` (checkbox) fa comparire un messaggio di rientro non punitivo al check-in successivo a una settimana fallita, poi si resetta. Nessun reward materiale nel rientro (evita l'incentivo perverso a fallire apposta per il bonus).

**Check-in automatico (anti-bugia)**: `POST /api/gym-webhook?secret=GYM_WEBHOOK_SECRET`. Fonte dati: app **Health Auto Export** (automazione REST API su nuovo allenamento) — scartato l'approccio via Apple Shortcuts nativo (property picker troppo inconsistente/fragile su iOS, vedi commit `4db2201` e precedenti per la storia). Body atteso: `{"data":{"workouts":[{"name":...,"start":"yyyy-MM-dd HH:mm:ss Z","duration":<secondi>, ...}]}}` (schema Health Auto Export v2, vedi [wiki ufficiale](https://github.com/Lybron/health-auto-export/wiki/API-Export---JSON-Format)). Prende l'ultimo elemento dell'array `workouts`. Validazione server: `start` deve essere oggi, `duration/60 >= 30` minuti. Rifiuti loggati su BotErrors col workout grezzo per debug.

## Bug noti / fix applicati
- `*` in merchant rompeva Markdown → retry senza `parse_mode`
- callback_data max 64 byte → `sc:{i}` non UUID
- Notion single-filter no `"and"` wrapper → bug silenzioso
- Whisper aggiunge punto finale → `rstrip(".!?,;:")` su text_lower
- "crei/elimini" (congiuntivo) non matchavano keyword → aggiunte forme verbali
- Prefissi conversazionali ("mi dici", "mostrami") strippati UNA VOLTA in cima al router
- `get_pending_reminders()` salta entry con prefix `PENDING:`
- Tick window 4 min (non 6) con cron 5 min → 1 fire max
