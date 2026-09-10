# AssistenteAI — Specifica Tecnica

## Stack
- Vercel serverless Flask WSGI, timeout 10s
- Groq: `openai/gpt-oss-120b` (routing/extraction/chat fallback), `openai/gpt-oss-20b` (categorizzazione spese), `whisper-large-v3-turbo` (vocali/video). Modelli reasoning: OGNI chiamata deve passare `"reasoning_effort": "low"` (altrimenti il ragionamento interno consuma tutto il `max_tokens` prima di scrivere la risposta, `content` resta vuoto) e `max_tokens` con margine ≥60 anche per estrazioni brevi (visto fallire a 20/10).
- Notion REST API (DB dati)
- Google Calendar API (OAuth2 refresh token) + iCal read
- wttr.in `j1` format (meteo), Google News RSS + ANSA (notizie)

## File principali
```
api/index.py     webhook Telegram, tick cron, send_telegram, transcribe_voice, POST /brief
router.py        routing msg → handler + prefissi conversazionali stripped
agents/
  budget.py      transazioni, categorie, budget alert, confronto mese, entrate, spese per periodo
  calendar.py    CRUD eventi Google Calendar + search + format (giorni IT)
  news.py        briefing mattutino, meteo IT (weatherCode map), forecast 3gg
  reminders.py   promemoria Notion (salta entry PENDING:)
  pending.py     stato temporaneo conferme (stesso DB Reminders, prefix PENDING:)
  errors.py      log errori su BotErrors DB Notion
  site_media.py    sostituzione PDF/foto su lineaverdeonline.com (allegato Telegram → WP REST)
  tracking.py      tracking pacchi via 17track.net (stesso DB Reminders, prefix PACCO:)
  case.py          ricerca casa: annunci + stato funnel (stesso DB Reminders, prefix CASA:)
```

## Notion DB IDs
| DB | ID |
|---|---|
| Transactions | `NOTION_DB_TRANSACTIONS` (env) |
| Categories | `NOTION_DB_CATEGORIES` (env) |
| MerchantMap | `c82a1f2a-a1dc-421b-aeb8-e0fc4e413354` |
| Reminders + Pending | `38a9d2a5-23ac-8158-badb-f41c332b13e4` |
| BotErrors | `38b9d2a5-23ac-81f5-935c-c9b665d4330f` |

## Env vars
```
TELEGRAM_TOKEN  TELEGRAM_CHAT_ID
NOTION_TOKEN  NOTION_DB_TRANSACTIONS  NOTION_DB_CATEGORIES
GROQ_API_KEY
GOOGLE_CLIENT_ID  GOOGLE_CLIENT_SECRET  GOOGLE_REFRESH_TOKEN
GOOGLE_CALENDAR_ICAL_URL
WP_APP_USER  WP_APP_PASSWORD   # Application Password WP (wp_16605717) per site_media.py
TRACK17_API_KEY   # 17track.net, tracking pacchi
BRIEF_SECRET   # POST /brief, inoltro testo esterno su Telegram
```

## Endpoint esterni
| Route | Auth | Uso |
|---|---|---|
| `POST /brief` | `?secret=` o `Authorization: Bearer` = `BRIEF_SECRET` | Body JSON `{"text": "..."}`, inoltra su Telegram riusando `send_telegram()` (chunking + Markdown + fallback plain). Per automazioni esterne che vogliono mandare un messaggio senza passare da Telegram direttamente. |

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
| h 8-22, 0<=m<=4 (orario) | check stato pacchi via 17track, notifica solo su cambio stato |

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

## Flusso sostituzione allegati sito (site_media.py)
0. `/sito` attiva la modalità (`enable_site_mode()`, flag `SITEMODE:ON` su Reminders DB, stesso pattern TICKLOCK di pending.py), `/end` la disattiva e pulisce eventuali pending `site_media_*` a metà. `handle_attachment` si rifiuta ("Manda /sito prima...") se la modalità non è attiva — evita che un allegato mandato per altri motivi finisca dentro il flusso di sostituzione senza bisogno di parole chiave ad ogni messaggio.
1. Documento/foto Telegram senza testo intercettato in `api/index.py` PRIMA del check `text and chat_id`, passato a `handle_attachment(file_id, filename, mime, caption)`.
2. Caption vuota → `save_pending("site_media_awaiting_description", {...})`, chiede "Dove lo metto?"; risposta testuale successiva viene letta come descrizione.
3. `start_replace_flow`: cerca pagine/articoli WP (`?search=`) che matchano la descrizione.
   - 0 risultati → si ferma, chiede il nome esatto della pagina.
   - >1 risultato → `save_pending("site_media_choose_page", {...candidates})`, mostra lista numerata; risposta numerica → `choose_page()`.
   - 1 risultato → cerca nel contenuto raw della pagina un link/immagine (`_find_reference`, regex + Groq se ambiguo) che corrisponda alla descrizione.
     - nessun match → si ferma ("non trovo niente da sostituire"), NON aggiunge mai contenuto nuovo.
     - match trovato → `save_pending("site_media_confirm", {...})`, mostra preview e chiede conferma sì/no.
4. "sì" → `handle_confirm()` → `confirm_replace()`: scarica il file da Telegram, lo carica su `/wp/v2/media` (nuovo URL, WP non sovrascrive un URL esistente), sostituisce il vecchio URL col nuovo nel contenuto della pagina, pubblica.

Regola fissa: solo sostituzioni di contenuto già esistente sul sito, mai creazione di contenuto nuovo in autonomia.

## Flusso tracking pacchi (tracking.py)
"traccia pacco <numero> [etichetta libera]" → `track_package()` registra su 17track (`/track/v2.2/register`, carrier omesso = auto-detect) e salva entry `PACCO:{json}` su Reminders DB (sent=False = attivo). Tick orario (8-22, `check_all_packages()`) interroga `/track/v2.2/gettrackinfo` per tutti i pacchi attivi, notifica su Telegram SOLO se lo status 17track (`OutForDelivery`/`Delivered`/`Exception`/...) è cambiato dall'ultimo check salvato; su stato terminale (Delivered/DeliveryFailure/Expired/Exception) marca sent=True e smette di pollare. "dove sono i miei pacchi" → `list_packages()` mostra stato attuale di tutti i pacchi attivi.

## Flusso ricerca casa (case.py)
Nessun tick/polling — solo su comando esplicito, entry `CASA:{json}` su Reminders DB (`sent` sempre False, non usato come gate qui — il filtro "attiva/scartata" è sul campo `stato` dentro il JSON, non su `sent`).
- "aggiungi casa `<testo libero>`" → Groq estrae link/prezzo/via/comune. Se via/comune mancano (link nudo, i portali immobiliari bloccano lo scraping server-side, 403 anche con UA browser) → flusso guidato `save_pending("new_house_awaiting_via"→"...comune"→"...prezzo")`, un campo alla volta, stesso pattern di `/viaggio`. Salvataggio diretto senza conferma finale (stato iniziale `nuova`).
- "casa `<via>` `<verbo>`" → `update_house_status()`, match fuzzy su via (substring in entrambe le direzioni), aggiornamento rapido one-shot senza aprire sessione. Verbo normalizzato a stato canonico: funnel `nuova → chiamato → vista → rivista → proposta`, più `scartata` (terminale, raggiungibile da qualsiasi stato).
- "casa `<via>`" (bare, senza verbo dopo) → apre **sessione di modifica** (`open_house_session`, flag `CASAMODE:<house_id>` su Reminders DB, stesso pattern SITEMODE di site_media.py ma con l'id casa nel titolo invece di ON/OFF fisso). Finché attiva: "via/comune/prezzo/link `<valore>`" aggiorna il campo, uno stato secco (es. "vista") aggiorna lo stato — niente bisogno di ripetere la via. Il gate è specifico (richiede prefix campo o parola-stato esatta), non intercetta testo generico, quindi il resto del bot funziona normale durante la sessione. `/end` chiude sia la sessione casa sia la modalità sito (condividono il comando).
- `/listacase` (alias: "lista case", "le mie case", "case") → tutte tranne `scartata`. "case scartate" → solo le scartate.

## Bug noti / fix applicati
- `*` in merchant rompeva Markdown → retry senza `parse_mode`
- callback_data max 64 byte → `sc:{i}` non UUID
- Notion single-filter no `"and"` wrapper → bug silenzioso
- Whisper aggiunge punto finale → `rstrip(".!?,;:")` su text_lower
- "crei/elimini" (congiuntivo) non matchavano keyword → aggiunte forme verbali
- Prefissi conversazionali ("mi dici", "mostrami") strippati UNA VOLTA in cima al router
- `get_pending_reminders()` salta entry con prefix `PENDING:`, `PACCO:` e `CASA:` (altrimenti finivano trattate come promemoria reali)
- Tick window 4 min (non 6) con cron 5 min → 1 fire max
- `_find_active_commitment` matchava con `name.startswith(merchant)`: la banca manda lo stesso piano BNPL con testo leggermente diverso tra una rata e l'altra (asterischi, suffissi tipo ".co" che vanno e vengono), match rigido falliva → piano duplicato per la stessa spesa. Fix: confronto normalizzato solo-alfanumerico, sottostringa in entrambe le direzioni (`_merchant_key`).
- `get_monthly_cashflow` calcolava sul mese di calendario (1° - ultimo giorno): lo stipendio non cade sempre il giorno 1 (es. arrivato l'8/07), quindi un mese fisso tagliava il ciclio di spesa reale a metà. Fix: periodo ancorato all'ultimo `merchant_raw == "Stipendio"` trovato in Transactions, fino ad oggi (fallback su mese calendario se nessuno stipendio trovato).
- `get_monthly_cashflow` sommava TUTTE le transazioni incluse le `Bonifico Uscita` (bonifici istantanei auto-iniziati, es. verso Fineco): il testo remittance della banca per questi bonifici viene generalizzato a "Bonifico Uscita"/categoria "Altro" in `_extract_merchant`, il vero destinatario non è mai salvato. **Risolto 2026-09-10**, vedi sezione "Trasferimenti interni" sotto — riconoscimento automatico per importo invece che per testo.
- **`llama-3.3-70b-versatile`/`llama-3.1-8b-instant` dismessi da Groq** (404 `model_not_found`, scoperto 2026-08-02): rotto tutto ciò che passa da Groq (fallback chat, estrazione transazioni/eventi/promemoria/entrate/case, categorizzazione spese). Sostituiti con `openai/gpt-oss-120b`/`openai/gpt-oss-20b` — ma sono modelli reasoning: senza `"reasoning_effort": "low"` il ragionamento interno consuma tutto `max_tokens` e `content` resta vuoto (`finish_reason: "length"`), anche con `reasoning_effort: "low"` i `max_tokens` bassi (10/20) restavano insufficienti. Fix: `reasoning_effort: "low"` su ogni chiamata + `max_tokens` alzato a ≥60 ovunque fosse più basso.

## Trasferimenti interni (PAC Fineco + top-up Revolut)
Isybank è diventato un conto di passaggio (deciso 2026-09-10): arriva lo stipendio, ~550-560€ (range tollerato 500-600) restano per il PAC Fineco, il resto va su Revolut come top-up fisso per le spese quotidiane. Revolut **non è sincronizzato** via Enable Banking (bloccato — vedi sotto) e la decisione è di non inseguirlo: Revolut fa già budgeting nativo sulle sue spese, il bot si occupa solo di Isybank/patrimonio/BNPL/flusso di cassa totale.

`enable_banking.py::_is_internal_transfer(amount_abs, booking_date, last_stipendio)`: quando `_extract_merchant` produce merchant `"Bonifico Uscita"`, controlla se l'importo rientra nel range PAC (500-600) oppure nel range del top-up Revolut (`stipendio - [500,600]`, entro 10gg dalla data stipendio) — se sì, categoria forzata `"Trasferimento"` invece di `"Altro"`. `get_monthly_spending`/`_get_spending`, `get_monthly_cashflow`/`_sum_cashflow_range` e `_get_transactions_since` escludono client-side la categoria `"Trasferimento"` (non è consumo né reddito).

**Tentativo di sync Revolut (fallito, 2026-09-10)**: Enable Banking collega Revolut (Italy) e cattura l'IBAN, ma il conto risulta in "Linked accounts" del pannello **senza UID** — 4 flussi di consenso puliti, sempre `status: AUTHORIZED` ma `accounts: []`. Non è errore utente (selezione conto confermata da screenshot), non è scope mancante (provato con `access.balances`/`access.transactions` espliciti), non è propagazione (ricontrollato a distanza). Segnalato al supporto Enable Banking (hello@enablebanking.com) via email 2026-09-10, in attesa di risposta. Altri percorsi provati e scartati: GoCardless Bank Account Data (registrazione bloccata), Salt Edge (Revolut assente dal catalogo reale — verificato con chiamata API diretta, 2247 provider, zero risultati), Revolut Business API (richiede piano Grow a pagamento + conto Business vero, non applicabile a un conto personale).

## TODO aperti (segnalati, non risolti)
- **`api/evening.py` è codice morto**: manda messaggi Telegram (budget alerts) ma `vercel.json` instrada TUTTO il traffico su `api/index.py` — nessuna route punta a `evening.py`, non è raggiungibile. Da decidere: rianimare come route dedicata, unire la logica in `index.py`, o rimuovere il file. Segnalato 2026-08-02, non toccato.
