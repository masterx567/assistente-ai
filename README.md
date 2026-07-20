# AssistenteAI

Bot Telegram personale, full-stack serverless: finanze, calendario, meteo/astronomia, studio, viaggi, palestra (gamification), promemoria — tutto guidato da linguaggio naturale (testo o vocale), zero comandi da imparare a memoria.

Risponde solo al chat ID del proprietario (`TELEGRAM_CHAT_ID`): non è un bot pubblico, è un assistente 1:1.

## Cosa fa

- **Finanze** — sync automatico transazioni da Isybank (Enable Banking / PSD2), categorizzazione, alert budget, piani rateali BNPL (Klarna/Scalapay/PayPal) con progress bar, riepiloghi settimanali/mensili con grafici, cashflow mensile
- **Calendario** — Google Calendar: crea/modifica/elimina/cerca eventi, reminder automatici pre-evento
- **Cielo & meteo** — previsioni meteo, briefing mattutino, modulo astronomia (fasi lunari, pianeti visibili, eventi eccezionali) su due località, calcolato con effemeridi reali (skyfield/NASA JPL)
- **Studio** — piano corsi con tracking avanzamento ed esami
- **Viaggi** — checklist con progress bar, spese di viaggio
- **Palestra** — check-in automatico (via Health Auto Export), XP/livelli/leghe, streak settimanale con scudi
- **Promemoria** — one-off o ricorrenti, gestiti via Notion
- **Pacchi** — tracking spedizioni (17track), avviso automatico su cambio stato ("in consegna", "consegnato")
- **Piante** — reminder irrigazione meteo-corretto

Un unico cron job (`/api/tick`, ogni 5 min) orchestra tutti i job schedulati (briefing, reminder, riepiloghi, check meteo/astro).

## Stack

- **Runtime**: Flask (WSGI) su Vercel serverless, timeout 10s
- **LLM**: Groq (`llama-3.3-70b-versatile` per routing/estrazione, `whisper-large-v3-turbo` per trascrizione vocali)
- **DB**: Notion (via REST API) — transazioni, categorie, promemoria, errori, stato gamification
- **Banca**: Enable Banking (standard Berlin Group PSD2) per sync Isybank
- **Calendario**: Google Calendar API (OAuth2)
- **Meteo/Astro**: wttr.in, skyfield (effemeridi JPL)
- **Grafici**: matplotlib (riepiloghi periodici)

## Struttura

```
api/index.py     webhook Telegram + cron tick + invio messaggi/grafici
router.py        instrada ogni messaggio all'handler giusto (ordine keyword critico)
agents/          budget, calendar, news, reminders, studio, travel, piante, gamification, astronomy, errors...
agents/SPEC.md   specifica tecnica completa (DB IDs, routing, bug noti, flussi di conferma)
```

## Comandi

Niente sintassi rigida, il router matcha keyword/frasi libere (vedi `router.py` per l'elenco completo). Riferimento rapido:

| Vuoi... | Dì (esempi) |
|---|---|
| Aiuto | `/help`, "aiuto", "cosa sai fare" |
| Saldo/spese/budget | "quanto ho speso", "budget", "quanto mi rimane in \<categoria\>", "ultime spese" |
| Confronto/proiezione | "mese scorso", "quanto spenderò", "flusso di cassa" |
| Patrimonio | "patrimonio", "andamento patrimonio" |
| Rate BNPL | "rate", "piano di ammortamento", "rate klarna" |
| Prestiti a persone | "ho prestato 50 a Mario", "restituito Mario", "prestiti" |
| Entrata | "ho ricevuto 1500 di stipendio", "aggiungi entrata" |
| Evento calendario | "aggiungi dentista venerdì alle 10", "elimina riunione", "sposta X a lunedì" |
| Impegni | "agenda oggi", "impegni domani", "eventi luglio", "quando ho \<nome\>" |
| Promemoria | "ricordami di chiamare Luigi domani alle 9" |
| Piano di studio | "piano esami", "esame SQL passato" |
| Nuovo viaggio | `/viaggio dal 1 al 3 settembre` |
| Checklist viaggio | `/checklist`, "aggiungi occhiali alla checklist", "fatto passaporto" |
| Budget viaggio | "budget viaggio" |
| Cielo (Cormano) | `/cielo`, "cosa vedo stanotte", "fase lunare" |
| Cielo (Alpe Ventina) | `/cielo valmalenco` |
| Prossima serata serena | "prossima serata serena" |
| Diario | "diario: giornata storta oggi", "diario di luglio" |
| Palestra | "palestra", "camminata" (check-in), "stato palestra" (scheda XP/livello) |
| Piante | `/piante`, "annaffiato vaso" |
| Notizie | "notizie", "briefing" |
| Pacchi | "traccia pacco \<numero\> \<etichetta\>", "dove sono i miei pacchi" |
| Conferma/annulla | "sì" / "no", "/fine" |

## Setup

Variabili d'ambiente richieste (vedi `agents/SPEC.md` per l'elenco completo):

```
TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, WEBHOOK_SECRET, CRON_SECRET
NOTION_TOKEN, NOTION_DB_TRANSACTIONS, NOTION_DB_CATEGORIES
GROQ_API_KEY
GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN
GYM_WEBHOOK_SECRET
TRACK17_API_KEY
```

Deploy su Vercel (build automatico da `vercel.json`), webhook Telegram puntato su `/api/webhook`, cron esterno (es. cron-job.org) che chiama `/api/tick` ogni 5 minuti.

Progetto personale, non pensato per riuso diretto da terzi (assunzioni hardcoded su formato Notion/valuta/fuso orario Europe/Rome).
