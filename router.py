import httpx
import os
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from agents.budget import get_monthly_spending, get_budget_alerts, format_spending_summary, format_alerts, add_transaction, delete_transaction, get_recent_transactions, lookup_merchant, get_category_budgets, get_all_categories, save_merchant_map, get_monthly_comparison, get_remaining_budget, get_transactions_by_period, add_income, get_amortization_table, save_account_balance, get_net_worth, add_loan, get_loans, get_month_projection, mark_loan_returned, get_net_worth_trend
import re as _re
from agents.news import get_morning_briefing
from agents.calendar import get_events, get_events_in_range, format_events, add_event, delete_event_by_title, rename_event, reschedule_event, search_events
from agents.reminders import add_reminder
from agents.pending import save_pending, get_pending, clear_pending
from agents.journal import add_journal_entry, get_journal_entries, format_journal_entries

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
ROME = ZoneInfo("Europe/Rome")

SYSTEM_PROMPT = """Sei un assistente finanziario e personale italiano. Rispondi sempre in italiano.
Sei conciso, utile e diretto. Usi emoji appropriati.

Puoi fare queste cose:
- Mostrare spese del mese corrente per categoria
- Avvisare su budget quasi esauriti o superati
- Dare notizie del giorno
- Gestire eventi del calendario (mostrare, aggiungere, eliminare)
- Rispondere a domande generali

Quando ricevi dati strutturati (spese, alert), formattali in modo chiaro e leggibile per Telegram (usa *grassetto* e • per liste).
"""


async def route_message(user_text: str) -> str:
    text_lower = user_text.lower().strip().rstrip(".!?,;:")

    # Rimuovi prefissi conversazionali per normalizzare il testo prima del routing
    _conv_prefixes = [
        "mi puoi dire ", "puoi dirmi ", "potresti dirmi ", "potresti dirci ",
        "mi dici ", "mi sai dire ", "sai dirmi ",
        "dimmi ", "dicci ",
        "mi mostri ", "mi mostra ", "mostrami ", "puoi mostrarmi ",
        "mi fai vedere ", "fammi vedere ",
        "mi dai ", "puoi darmi ", "dammi ",
        "vorrei sapere ", "voglio sapere ", "vorrei vedere ",
        "che ne sai di ", "sai qualcosa su ",
    ]
    for _p in _conv_prefixes:
        if text_lower.startswith(_p):
            text_lower = text_lower[len(_p):]
            break

    # Cedimento dipendenza (resetta streak) — controllalo prima del diario generico
    if "ho ceduto" in text_lower:
        note_match = _re.search(r"ho ceduto\s*(.*)", text_lower)
        note = note_match.group(1).strip(" ,.-") if note_match else ""
        return await add_journal_entry(note or "Cedimento.", cedimento=True)

    # Lettura diario: "mostra/rileggi diario <periodo>" oppure "diario di/del <periodo>" (solo periodo, non prosa)
    _period_only_re = _re.compile(
        r"^(di |del |della |questo |questa |ultima |ultimo |per )*"
        r"(settimana( scorsa)?|mese( scorso)?|gennaio|febbraio|marzo|aprile|maggio|giugno|"
        r"luglio|agosto|settembre|ottobre|novembre|dicembre)\.?$"
    )
    _explicit_read = _re.match(r"^\s*(mostra|rileggi)\s+diario\s+(.+)", text_lower, _re.DOTALL)
    _bare_diario = _re.match(r"^\s*diario\s*[:.,]?\s*(.+)", text_lower, _re.DOTALL)
    if _explicit_read:
        entries, start, end = await get_journal_entries(_explicit_read.group(2).strip())
        return format_journal_entries(entries, start, end)
    if _bare_diario and _period_only_re.match(_bare_diario.group(1).strip()):
        entries, start, end = await get_journal_entries(_bare_diario.group(1).strip())
        return format_journal_entries(entries, start, end)

    # Diario libero: "diario: <testo>" / "diario. <testo>" / "diario <testo>"
    diario_match = _re.search(r"^\s*diario\s*[:.,]?\s*(.+)", user_text, _re.IGNORECASE | _re.DOTALL)
    if diario_match:
        return await add_journal_entry(diario_match.group(1).strip())

    # Risposta a domanda patrimonio Fineco (es. "1250", "fineco 6008.16", "ho 1250,50 su fineco")
    _num_match = _re.search(r"\d+[.,]\d+|\d+", text_lower)
    if _num_match:
        pending = await get_pending()
        if pending and pending["action"] == "fineco_balance":
            await clear_pending(pending["id"])
            amount = float(_num_match.group().replace(",", "."))
            await save_account_balance("Fineco ETF", amount, "investment")
            return await get_net_worth()

    # Conferma/annulla azione pending
    _confirm_kw = {"sì", "si", "yes", "confermo", "ok", "vai", "esegui", "procedi", "fatto", "perfetto", "giusto", "esatto", "corretto"}
    _cancel_kw  = {"no", "annulla", "stop", "abort", "lascia perdere", "lasciare perdere", "non fare", "non voglio"}
    if text_lower in _confirm_kw:
        return await handle_confirm()
    if text_lower in _cancel_kw or any(text_lower.startswith(w) for w in ("no ", "annull", "lascia perd")):
        return await handle_cancel()

    # Entrate (controlla PRIMA delle transazioni spese)
    income_kw = [
        "ho ricevuto", "ho guadagnato", "ho incassato",
        "stipendio", "busta paga", "salario",
        "entrata di", "entrate di", "entrata da",
        "accredito", "accreditato", "bonifico ricevuto",
        "rimborso", "freelance", "fattura pagata",
        "aggiungi entrata", "registra entrata", "nuova entrata", "segna entrata",
    ]
    if any(w in text_lower for w in income_kw):
        return await handle_add_income(user_text)

    # Elimina transazione (controlla PRIMA del calendario)
    del_tx_kw = [
        "elimina transazione", "elimini transazione", "elimina la transazione",
        "cancella transazione", "cancelli transazione", "cancella la transazione",
        "togli transazione", "rimuovi transazione", "rimuovimi transazione",
        "elimina spesa", "cancella spesa", "togli spesa", "rimuovi spesa",
        "elimina acquisto", "cancella acquisto",
    ]
    if any(w in text_lower for w in del_tx_kw):
        return await handle_delete_transaction(user_text)

    # Aggiungi transazione da chat (controlla PRIMA del calendario)
    tx_kw = [
        "ho speso", "ho pagato", "ho comprato", "ho acquistato",
        "spesa di", "pagato ", "speso ", "costato ", "è costato",
        "crea transazione", "crei transazione", "creami transazione",
        "aggiungi transazione", "aggiungimi transazione", "inserisci transazione",
        "nuova transazione", "registra transazione", "segna transazione",
        "aggiungi spesa", "aggiungimi spesa", "nuova spesa", "inserisci spesa",
        "registra spesa", "segna spesa", "fatto la spesa",
    ]
    _tx_nouns = ["transazione", "spesa", "acquisto", "pagamento"]
    _tx_verbs = ["crea", "crei", "creami", "aggiungi", "aggiungimi", "inserisci",
                 "inseriscimi", "registra", "segna", "metti", "mettimi", "aggiungi"]
    _has_tx_noun = any(w in text_lower for w in _tx_nouns)
    _has_tx_verb = any(w in text_lower for w in _tx_verbs)
    if any(w in text_lower for w in tx_kw) or (_has_tx_noun and _has_tx_verb):
        return await handle_add_transaction(user_text)

    # Prossimi impegni on-demand (oggi / domani)
    today_kw = [
        "prossimi impegni", "agenda oggi", "cosa ho oggi", "impegni oggi",
        "cosa faccio oggi", "ho oggi", "ho domani", "cosa ho domani",
        "impegni domani", "agenda domani", "cosa succede oggi", "cosa succede domani",
    ]
    if any(w in text_lower for w in today_kw):
        from agents.calendar import get_today_events
        ev = await get_today_events()
        return ev if ev else "Nessun impegno oggi né domani."

    # Impegni per mese specifico (es. "eventi luglio", "agenda agosto")
    _months_cal = {
        "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4,
        "maggio": 5, "giugno": 6, "luglio": 7, "agosto": 8,
        "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
    }
    _cal_ctx = ["event", "agenda", "impegn", "appuntament", "calendar", "cosa ho", "cosa c'è", "mi dici"]
    matched_month = next((m for m in _months_cal if m in text_lower), None)
    if matched_month and any(w in text_lower for w in _cal_ctx):
        import calendar as _cal_mod
        from datetime import date as _date
        now_year = datetime.now().year
        mon = _months_cal[matched_month]
        # Se il mese è già passato quest'anno, prendi il prossimo anno
        if mon < datetime.now().month:
            now_year += 1
        last_day = _cal_mod.monthrange(now_year, mon)[1]
        start = _date(now_year, mon, 1)
        end = _date(now_year, mon, last_day)
        events = await get_events_in_range(start, end)
        if not events:
            return f"📅 Nessun evento in {matched_month.capitalize()} {now_year}."
        lines = [f"📅 *Eventi {matched_month.capitalize()} {now_year}:*\n"]
        for ev in events:
            time_str = f" alle {ev['time']}" if ev.get("time") else ""
            lines.append(f"• {ev['date'].strftime('%d/%m')}{time_str} — {ev['title']}")
        return "\n".join(lines)

    # Impegni prossimo mese / settimana prossima
    future_kw = [
        "prossimo mese", "mese prossimo", "impegni del mese",
        "settimana prossima", "prossima settimana", "prossime settimane",
        "questo mese", "fine mese",
    ]
    if any(w in text_lower for w in future_kw):
        days = 30 if "mese" in text_lower else 14
        events = await get_events(days_ahead=days)
        return format_events(events)

    # Promemoria
    reminder_kw = [
        "ricordami", "ricorda di", "ricordati", "ricordamelo",
        "promemoria", "reminder", "non dimenticare", "non mi far dimenticare",
        "avvisami", "avvertimi", "mandami un reminder",
    ]
    if any(w in text_lower for w in reminder_kw):
        return await handle_reminder(user_text)

    # Piani di ammortamento BNPL (Klarna/Scalapay/rate)
    amortization_kw = [
        "piano di ammortamento", "piani di ammortamento", "piano ammortamento",
        "rate klarna", "rate scalapay", "pagamenti a rate", "quante rate",
        "rate rimanenti", "rate rimaste", "quanto manca alle rate",
        "rate attive", "rate in corso", "le mie rate", "mie rate",
        "rate da pagare", "rate aperte", "rate", "bnpl",
    ]
    if any(w in text_lower for w in amortization_kw):
        return await get_amortization_table()

    # Andamento patrimonio nel tempo (controlla PRIMA di "patrimonio" generico)
    if any(w in text_lower for w in ["andamento patrimonio", "storico patrimonio", "trend patrimonio"]):
        return await get_net_worth_trend()

    # Patrimonio netto
    if any(w in text_lower for w in ["patrimonio", "quanto vale il mio patrimonio", "net worth"]):
        return await get_net_worth()

    # Previsione fine mese
    if any(w in text_lower for w in ["previsione fine mese", "quanto spenderò", "proiezione spesa", "proiezione fine mese", "quanto spendero"]):
        return await get_month_projection()

    # Prestito restituito
    returned_match = _re.search(r"restituito\s+(\w+)", text_lower)
    if returned_match:
        return await mark_loan_returned(returned_match.group(1))

    # Prestiti dati a persone
    loan_match = _re.search(r"(?:ho prestato|prestato|presto)\s+(?:€\s?)?(\d+(?:[.,]\d+)?)\s?€?\s*(?:a|per)\s+(\w+)", text_lower)
    if loan_match:
        amount = float(loan_match.group(1).replace(",", "."))
        person = loan_match.group(2)
        return await add_loan(person, amount)
    if any(w in text_lower for w in ["prestiti", "chi mi deve", "prestiti dati", "prestiti attivi"]):
        return await get_loans()

    # Budget rimanente per categoria
    remaining_kw = [
        "quanto mi rimane", "quanto rimane", "budget rimanente",
        "quanto posso ancora spendere", "quanto ho ancora",
        "mi rimane in", "rimasto in", "rimasto nel budget",
    ]
    if any(w in text_lower for w in remaining_kw):
        cat_query = await _extract_category_query(user_text)
        return await get_remaining_budget(cat_query)

    # Ultime spese con filtro periodo opzionale
    recent_kw = [
        "ultime spese", "ultime transazioni", "ultimi acquisti",
        "cosa ho speso", "cosa ho pagato", "cosa ho comprato",
        "mostra spese", "mostrami spese", "vedi spese", "storico spese",
        "ultime uscite", "le mie spese", "i miei acquisti",
        "spese di ", "spese del mese", "spese questa settimana",
    ]
    if any(w in text_lower for w in recent_kw):
        period_kw = ["settimana", "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
                     "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"]
        has_period = any(w in text_lower for w in period_kw) or "mese" in text_lower
        if has_period:
            txs, start, end = await get_transactions_by_period(text_lower)
            label = f"{start.strftime('%d/%m')} – {end.strftime('%d/%m/%Y')}"
        else:
            txs = await get_recent_transactions(10)
            label = "ultime 10"
        if not txs:
            return "Nessuna spesa nel periodo."
        lines = [f"📋 *Spese ({label})*\n"]
        for t in txs:
            name = t['name'].replace('*', '')
            lines.append(f"• {t['date']} — *{name}* €{t['amount']:.2f}")
        return "\n".join(lines)

    # Confronto mese corrente vs mese scorso
    compare_kw = [
        "confronto mese", "vs mese", "mese scorso", "mese precedente",
        "rispetto al mese", "confronta mese", "paragona mese",
        "ho speso di più", "ho speso di meno", "spendo di più",
    ]
    if any(w in text_lower for w in compare_kw):
        return await get_monthly_comparison()

    # Budget / spese
    if any(w in text_lower for w in ["spes", "budget", "quanto", "soldi", "spendo", "categor", "mese"]):
        spending = await get_monthly_spending()
        alerts = await get_budget_alerts()
        context = format_spending_summary(spending)
        if alerts:
            context += "\n\n" + format_alerts(alerts)
        return await ask_groq(user_text, context)

    # Azioni calendario (aggiungi / elimina / modifica)
    add_kw = [
        "aggiungi", "aggiungimi", "segna", "segnami",
        "metti in calendario", "mettimi in calendario",
        "crea", "crei", "creami",
        "prenota", "prenotami",
        "nuovo evento", "nuova riunione", "nuovo appuntamento",
        "inserisci", "inseriscimi",
        "pianifica", "pianificami", "schedula",
        "fissa", "fissami",
    ]
    del_kw = [
        "elimina", "elimini", "eliminami",
        "cancella", "cancelli", "cancellami",
        "rimuovi", "rimuovimi",
        "togli", "toglimi",
        "annulla evento", "cancella evento",
    ]
    mod_kw = [
        "modifica", "modificami", "modificare",
        "rinomina", "rinominami",
        "cambia nome", "cambia orario", "cambia data",
        "aggiorna evento", "aggiorna appuntamento",
        "sposta", "spostami", "spostare",
        "posticipa", "anticipa",
    ]
    has_add = any(w in text_lower for w in add_kw)
    has_del = any(w in text_lower for w in del_kw)
    has_mod = any(w in text_lower for w in mod_kw)

    if has_add or has_del or has_mod:
        return await handle_calendar_action(user_text)

    # Ricerca eventi per nome
    search_kw = [
        "quando ho", "quando c'è", "quando ci sono", "quando è",
        "quando le", "quando i ", "quando il ", "quando la ", "quando lo ", "quando gli ",
        "cerca event", "trovami",
        "tutti gli event", "tutte le volte", "quante volte",
        "ho in programma", "ho schedulato",
    ]
    if any(w in text_lower for w in search_kw):
        query = await _extract_search_query(user_text)
        if query:
            results = await search_events(query, days_ahead=365)
            if results:
                lines = [f"🔍 *Risultati per '{query}':*\n"]
                for ev in results:
                    time_str = f" alle {ev['time']}" if ev.get("time") else ""
                    lines.append(f"• {ev['date'].strftime('%d/%m/%Y')}{time_str}: {ev['title']}")
                return "\n".join(lines)
            return f"Nessun evento trovato con '{query}' nei prossimi 12 mesi."

    # Mostra calendario
    cal_keywords = [
        "impegn", "calendar", "agenda", "appuntament", "event",
        "settiman", "da fare", "ho da", "cosa faccio", "cosa ho",
        "in programma", "schedulat", "orario",
    ]
    if any(w in text_lower for w in cal_keywords):
        events = await get_events(days_ahead=7)
        return format_events(events)

    # Notizie
    news_kw = [
        "notizi", "news", "succede", "aggiornament",
        "giornale", "briefing", "titoli", "attualità",
        "cosa è successo", "cosa succede nel mondo",
    ]
    if any(w in text_lower for w in news_kw):
        briefing = await get_morning_briefing()
        return briefing

    return await ask_groq(user_text, "")


async def _extract_events_from_text(user_text: str) -> list[dict]:
    """Usa Groq per estrarre una lista di azioni calendario dal testo."""
    today = datetime.now(ROME)
    prompt = f"""Oggi è {today.strftime('%A %d/%m/%Y')}, ora {today.strftime('%H:%M')}.

Analizza il testo e restituisci un array JSON con tutte le azioni da eseguire.
Ogni azione ha:
- "action": "add", "delete", "rename" o "reschedule"
- "title": nome COMPLETO dell'evento (per add/delete/reschedule)
- "old_title": nome attuale (solo per rename)
- "new_title": nuovo nome (solo per rename)
- "date": "YYYY-MM-DD" (per add e reschedule)
- "time": "HH:MM" (per add e reschedule, default "09:00" se non specificato)

Interpreta date relative in italiano (oggi, domani, lunedì, ecc.).
IMPORTANTE: le parole "impegno", "evento", "appuntamento" sono parole generiche, NON fanno parte del titolo. Ignorale nel titolo.
Rispondi SOLO con il JSON array, zero altro testo.

Esempi:
- "aggiungi dentista domani alle 10" → [{{"action":"add","title":"dentista","date":"{(today + timedelta(days=1)).strftime('%Y-%m-%d')}","time":"10:00"}}]
- "elimina riunione e aggiungi palestra venerdì alle 18" → [{{"action":"delete","title":"riunione"}},{{"action":"add","title":"palestra","date":"2026-06-27","time":"18:00"}}]
- "modifica nome da vecchio nome a nuovo nome" → [{{"action":"rename","old_title":"vecchio nome","new_title":"nuovo nome"}}]
- "rinomina dentista in visita medica" → [{{"action":"rename","old_title":"dentista","new_title":"visita medica"}}]
- "sposta dentista a venerdì alle 15" → [{{"action":"reschedule","title":"dentista","date":"2026-06-27","time":"15:00"}}]
- "cambia orario palestra a lunedì alle 9" → [{{"action":"reschedule","title":"palestra","date":"2026-06-29","time":"09:00"}}]

Testo: {user_text}"""

    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={"model": "llama-3.3-70b-versatile",
                  "messages": [{"role": "user", "content": prompt}],
                  "max_tokens": 300, "temperature": 0},
        )
    raw = r.json()["choices"][0]["message"]["content"].strip()
    start = raw.find("[")
    end = raw.rfind("]") + 1
    return json.loads(raw[start:end])


async def handle_calendar_action(user_text: str) -> str:
    try:
        actions = await _extract_events_from_text(user_text)
        results = []
        for a in actions:
            if a["action"] == "add":
                dt = datetime.strptime(f"{a['date']} {a['time']}", "%Y-%m-%d %H:%M").replace(tzinfo=ROME)
                results.append(await add_event(a["title"], dt))
            elif a["action"] == "delete":
                results.append(await delete_event_by_title(a["title"]))
            elif a["action"] == "rename":
                results.append(await rename_event(a["old_title"], a["new_title"]))
            elif a["action"] == "reschedule":
                results.append(await reschedule_event(a["title"], a["date"], a["time"]))
        return "\n".join(results) if results else "Nessuna azione eseguita."
    except Exception:
        return "Non ho capito. Esempi: 'aggiungi dentista venerdì alle 10', 'elimina riunione'"


async def handle_add_transaction(user_text: str) -> str:
    today = datetime.now(ROME)
    prompt = f"""Oggi è {today.strftime('%Y-%m-%d')}.
Estrai dal testo: importo (numero positivo), nome merchant/negozio COMPLETO (includi tutto il nome, es. "mcdonalds test"), data (YYYY-MM-DD, default oggi).
Rispondi SOLO con JSON: {{"amount": 12.50, "merchant": "McDonald's Test", "date": "2026-06-25"}}
IMPORTANTE: il merchant è il nome esatto del negozio/servizio scritto nel testo, non inventare.
Testo: {user_text}"""
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(GROQ_URL,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={"model": "llama-3.3-70b-versatile",
                  "messages": [{"role": "user", "content": prompt}],
                  "max_tokens": 80, "temperature": 0})
    raw = r.json()["choices"][0]["message"]["content"].strip()
    start = raw.find("{"); end = raw.rfind("}") + 1
    data = json.loads(raw[start:end])
    merchant = data["merchant"]
    amount = float(data["amount"])
    date_str = data.get("date", today.strftime("%Y-%m-%d"))
    cat = await lookup_merchant(merchant)
    await save_pending("add_tx", {"merchant": merchant, "amount": amount, "date": date_str, "cat_id": cat["cat_id"]})
    return (f"➕ Vuoi aggiungere:\n"
            f"• *{merchant}* -€{amount:.2f}\n"
            f"• Data: {date_str}\n"
            f"• Categoria: *{cat['cat_name']}*\n\n"
            f"Rispondi *sì* per confermare o *no* per annullare.")


async def handle_delete_transaction(user_text: str) -> str:
    today = datetime.now(ROME)
    prompt = f"""Oggi è {today.strftime('%Y-%m-%d')}.
Dal testo estrai: nome merchant/negozio, importo (opzionale), data (opzionale, YYYY-MM-DD).
IGNORA le parole di comando come: elimina, cancella, transazione, spesa, togli, rimuovi.
Il merchant è solo il nome del negozio/servizio, non le parole di comando.
Esempi:
- "elimina transazione mcdonalds test 3 euro" → {{"merchant": "mcdonalds test", "amount": 3.0}}
- "cancella spesa netflix" → {{"merchant": "netflix"}}
- "elimina transazione amazon del 20 giugno" → {{"merchant": "amazon", "date": "2026-06-20"}}
Rispondi SOLO con JSON. Se importo o data non presenti, ometti il campo.
Testo: {user_text}"""
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(GROQ_URL,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={"model": "llama-3.3-70b-versatile",
                  "messages": [{"role": "user", "content": prompt}],
                  "max_tokens": 80, "temperature": 0})
    raw = r.json()["choices"][0]["message"]["content"].strip()
    start = raw.find("{"); end = raw.rfind("}") + 1
    data = json.loads(raw[start:end])
    merchant = data["merchant"]
    amount = data.get("amount")
    date_str = data.get("date")
    await save_pending("del_tx", {"merchant": merchant, "amount": amount, "date": date_str})
    details = f"• *{merchant}*"
    if amount:
        details += f" €{float(amount):.2f}"
    if date_str:
        details += f" del {date_str}"
    return (f"🗑️ Vuoi eliminare:\n{details}\n\n"
            f"Rispondi *sì* per confermare o *no* per annullare.")


async def handle_confirm() -> str | dict:
    pending = await get_pending()
    if not pending:
        return "Nessuna azione in attesa di conferma."
    action = pending["action"]
    payload = pending["payload"]
    await clear_pending(pending["id"])
    if action == "add_tx":
        result = await add_transaction(payload["merchant"], float(payload["amount"]), payload.get("date"), payload.get("cat_id"))
        # Offri di salvare nel MerchantMap se merchant non era già mappato
        original_lookup = await lookup_merchant(payload["merchant"])
        if payload.get("cat_id") and original_lookup["cat_id"] != payload.get("cat_id"):
            await save_pending("save_map", {"merchant": payload["merchant"], "cat_id": payload["cat_id"]})
            cat_names = await get_all_categories()
            cat_name = next((c["name"] for c in cat_names if c["id"] == payload["cat_id"]), "?")
            return {
                "text": (f"{result}\n\n"
                         f"Vuoi salvare *{payload['merchant']}* → *{cat_name}* nel MerchantMap\n"
                         f"per le prossime volte?"),
                "markup": {"inline_keyboard": [[
                    {"text": "✅ Sì, salva", "callback_data": "sm:1"},
                    {"text": "❌ No", "callback_data": "sm:0"},
                ]]}
            }
        return result
    elif action == "del_tx":
        return await delete_transaction(payload["merchant"], payload.get("amount"), payload.get("date"))
    elif action == "add_income":
        return await add_income(payload["source"], float(payload["amount"]), payload.get("date"))
    elif action == "save_map":
        await save_merchant_map(payload["merchant"], payload["cat_id"])
        return "✅ Merchant salvato nel MerchantMap."
    return "Azione sconosciuta."


async def handle_cancel() -> dict:
    pending = await get_pending()
    if not pending:
        return {"text": "Nessuna azione da annullare."}
    # Se era add_tx mostra bottoni categoria — NON cancellare ora, lo farà handle_category_callback al click
    if pending["action"] == "add_tx":
        payload = pending["payload"]
        cats = await get_all_categories()
        # Bottoni a griglia 2 per riga, callback_data = "sc:{index}" (max 5 byte)
        rows = []
        row = []
        for i, c in enumerate(cats):
            row.append({"text": c["name"], "callback_data": f"sc:{i}"})
            if len(row) == 2:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
        return {
            "text": (f"❌ Annullato.\n\n"
                     f"Vuoi riprovare con una categoria diversa?\n"
                     f"• *{payload['merchant']}* -€{float(payload['amount']):.2f}\n\n"
                     f"Scegli categoria:"),
            "markup": {"inline_keyboard": rows},
        }
    await clear_pending(pending["id"])
    return {"text": "❌ Annullato."}


async def handle_category_callback(cat_index: int) -> dict:
    """Callback quando utente clicca bottone categoria."""
    pending = await get_pending()
    if not pending or pending["action"] != "add_tx":
        return {"text": "Sessione scaduta, rimanda il comando."}
    await clear_pending(pending["id"])
    payload = pending["payload"]
    # Ricarica categorie e prendi quella all'indice
    cats = await get_all_categories()
    if cat_index >= len(cats):
        return {"text": "Categoria non valida, rimanda il comando."}
    cat = cats[cat_index]
    payload["cat_id"] = cat["id"]
    await save_pending("add_tx", payload)
    return {
        "text": (f"➕ Vuoi aggiungere:\n"
                 f"• *{payload['merchant']}* -€{float(payload['amount']):.2f}\n"
                 f"• Data: {payload.get('date', 'oggi')}\n"
                 f"• Categoria: *{cat['name']}*\n\n"
                 f"Rispondi *sì* per confermare o *no* per annullare.")
    }


async def handle_reminder(user_text: str) -> str:
    today = datetime.now(ROME)
    prompt = f"""Oggi è {today.strftime('%A %d/%m/%Y')}, ora {today.strftime('%H:%M')}.
Estrai dal testo cosa ricordare, data e ora.
Rispondi SOLO con JSON: {{"text": "cosa ricordare", "date": "YYYY-MM-DD", "time": "HH:MM"}}
Default time: 09:00. Interpreta date relative italiane (domani, lunedì, tra X minuti, tra X ore, ecc.).
Testo: {user_text}"""
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(GROQ_URL,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={"model": "llama-3.3-70b-versatile",
                  "messages": [{"role": "user", "content": prompt}],
                  "max_tokens": 80, "temperature": 0})
    raw = r.json()["choices"][0]["message"]["content"].strip()
    start = raw.find("{"); end = raw.rfind("}") + 1
    data = json.loads(raw[start:end])
    dt = datetime.strptime(f"{data['date']} {data['time']}", "%Y-%m-%d %H:%M").replace(tzinfo=ROME)
    return await add_reminder(data["text"], dt)


async def _extract_search_query(user_text: str) -> str:
    """Estrae la parola chiave di ricerca dal testo con Groq."""
    prompt = f"""Estrai il termine di ricerca per il calendario dal testo.
Priorità: nomi propri di persona o servizio > attività specifica > argomento generico.
IGNORA: articoli (il, la, le, lo, i, gli, un, una), preposizioni (di, da, in, a, per, con, su), verbi generici (ho, ho, è, ci sono, dici, sai, quando, mi, ti, che), parole come evento/impegno/appuntamento/lezione.
Esempi:
- "quando ho lezioni di inglese con Kenner" → kenner
- "quando ho il dentista" → dentista
- "mi dici quando le ferie" → ferie
- "mi dici le ferie" → ferie
- "cerca tutti gli eventi palestra" → palestra
- "quando ho preply" → preply
- "trovami ferie" → ferie
- "quante volte ho pilates questo mese" → pilates
Rispondi SOLO con il termine (1-2 parole max), zero altro testo.
Testo: {user_text}"""
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={"model": "llama-3.3-70b-versatile",
                  "messages": [{"role": "user", "content": prompt}],
                  "max_tokens": 20, "temperature": 0},
        )
    return r.json()["choices"][0]["message"]["content"].strip().lower()


async def handle_add_income(user_text: str) -> str:
    """Estrae source e importo dal testo e aggiunge entrata con conferma."""
    today = datetime.now(ROME)
    prompt = f"""Estrai source (nome entrata/fonte) e importo da questo testo.
Rispondi SOLO con JSON: {{"source": "nome", "amount": 123.45, "date": "YYYY-MM-DD"}}
Date relative: oggi={today.strftime('%Y-%m-%d')}.
IGNORA parole come: ho ricevuto, ho guadagnato, entrata, aggiungi, registra.
Esempi:
- "ho ricevuto 1500 euro di stipendio" → {{"source": "Stipendio", "amount": 1500, "date": "{today.strftime('%Y-%m-%d')}"}}
- "rimborso spese 200 euro" → {{"source": "Rimborso spese", "amount": 200, "date": "{today.strftime('%Y-%m-%d')}"}}
- "freelance 500 euro" → {{"source": "Freelance", "amount": 500, "date": "{today.strftime('%Y-%m-%d')}"}}
Testo: {user_text}"""
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(GROQ_URL,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={"model": "llama-3.3-70b-versatile",
                  "messages": [{"role": "user", "content": prompt}],
                  "max_tokens": 80, "temperature": 0})
    raw = r.json()["choices"][0]["message"]["content"].strip()
    start = raw.find("{"); end_idx = raw.rfind("}") + 1
    data = json.loads(raw[start:end_idx])
    source = data.get("source", "Entrata")
    amount = float(data.get("amount", 0))
    date_str = data.get("date", today.strftime("%Y-%m-%d"))
    await save_pending("add_income", {"source": source, "amount": amount, "date": date_str})
    return (f"💰 Vuoi aggiungere entrata:\n"
            f"• *{source}* +€{amount:.2f}\n"
            f"• Data: {date_str}\n\n"
            f"Rispondi *sì* per confermare o *no* per annullare.")


async def _extract_category_query(user_text: str) -> str:
    """Estrae il nome della categoria da domande tipo 'quanto mi rimane in shopping'."""
    prompt = f"""Estrai solo il nome della categoria di spesa dal testo.
Esempi:
- "quanto mi rimane nel budget shopping" → shopping
- "quanto posso ancora spendere in cibo" → cibo
- "budget rimanente viaggi" → viaggi
- "quanto ho ancora per le uscite" → uscite
Rispondi SOLO con il nome categoria (1-2 parole), zero altro testo.
Testo: {user_text}"""
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(GROQ_URL,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={"model": "llama-3.3-70b-versatile",
                  "messages": [{"role": "user", "content": prompt}],
                  "max_tokens": 20, "temperature": 0})
    return r.json()["choices"][0]["message"]["content"].strip().lower()


async def ask_groq(user_text: str, context: str = "") -> str:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if context:
        messages.append({"role": "system", "content": f"Dati disponibili:\n{context}"})
    messages.append({"role": "user", "content": user_text})

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={"model": "llama-3.3-70b-versatile", "messages": messages, "max_tokens": 500, "temperature": 0.7},
        )
        if r.status_code != 200:
            return f"Errore nella risposta ({r.status_code}). Riprova."
        return r.json()["choices"][0]["message"]["content"]
