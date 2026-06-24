import httpx
import os
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from agents.budget import get_monthly_spending, get_budget_alerts, format_spending_summary, format_alerts
from agents.news import get_morning_briefing
from agents.calendar import get_events, format_events, add_event, delete_event_by_title

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
    text_lower = user_text.lower()

    # Budget / spese
    if any(w in text_lower for w in ["spes", "budget", "quanto", "soldi", "spendo", "categor", "mese"]):
        spending = await get_monthly_spending()
        alerts = await get_budget_alerts()
        context = format_spending_summary(spending)
        if alerts:
            context += "\n\n" + format_alerts(alerts)
        return await ask_groq(user_text, context)

    # Aggiungi evento
    add_keywords = ["aggiungi", "aggiungi evento", "segna", "metti in calendario", "crea evento", "prenota", "nuovo evento"]
    if any(w in text_lower for w in add_keywords):
        return await handle_add_event(user_text)

    # Elimina evento
    del_keywords = ["elimina", "cancella", "rimuovi", "togli", "delete"]
    if any(w in text_lower for w in del_keywords) and any(w in text_lower for w in ["event", "appuntament", "impegn"]):
        return await handle_delete_event(user_text)

    # Mostra calendario
    cal_keywords = ["impegn", "calendar", "agenda", "appuntament", "event", "settiman", "da fare", "ho da", "cosa faccio", "cosa ho"]
    if any(w in text_lower for w in cal_keywords):
        events = await get_events(days_ahead=7)
        return format_events(events)

    # Notizie
    if any(w in text_lower for w in ["notizi", "news", "succede", "aggiornament", "giornale", "briefing"]):
        briefing = await get_morning_briefing()
        return briefing

    return await ask_groq(user_text, "")


async def _extract_events_from_text(user_text: str) -> list[dict]:
    """Usa Groq per estrarre una lista di azioni calendario dal testo."""
    today = datetime.now(ROME)
    prompt = f"""Oggi è {today.strftime('%A %d/%m/%Y')}, ora {today.strftime('%H:%M')}.

Analizza il testo e restituisci un array JSON con tutte le azioni da eseguire.
Ogni azione ha:
- "action": "add" o "delete"
- "title": il nome COMPLETO dell'evento (tutte le parole che lo descrivono, non solo la prima)
- "date": "YYYY-MM-DD" (solo per add)
- "time": "HH:MM" (solo per add, default "09:00" se non specificato)

Interpreta date relative in italiano (oggi, domani, lunedì, ecc.).
Rispondi SOLO con il JSON array, zero altro testo.

Esempi:
- "aggiungi dentista domani alle 10" → [{{"action":"add","title":"dentista","date":"2026-06-25","time":"10:00"}}]
- "elimina riunione e aggiungi palestra venerdì alle 18" → [{{"action":"delete","title":"riunione"}},{{"action":"add","title":"palestra","date":"2026-06-27","time":"18:00"}}]
- "aggiungi arriva ci oggi alle 17:30" → [{{"action":"add","title":"arriva ci","date":"2026-06-24","time":"17:30"}}]

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


async def handle_add_event(user_text: str) -> str:
    try:
        actions = await _extract_events_from_text(user_text)
        results = []
        for a in actions:
            if a["action"] == "add":
                dt = datetime.strptime(f"{a['date']} {a['time']}", "%Y-%m-%d %H:%M").replace(tzinfo=ROME)
                results.append(await add_event(a["title"], dt))
            elif a["action"] == "delete":
                results.append(await delete_event_by_title(a["title"]))
        return "\n".join(results) if results else "Nessuna azione eseguita."
    except Exception:
        return "Non ho capito. Scrivi tipo: 'aggiungi dentista venerdì alle 10'"


async def handle_delete_event(user_text: str) -> str:
    try:
        actions = await _extract_events_from_text(user_text)
        results = []
        for a in actions:
            if a["action"] == "delete":
                results.append(await delete_event_by_title(a["title"]))
            elif a["action"] == "add":
                dt = datetime.strptime(f"{a['date']} {a['time']}", "%Y-%m-%d %H:%M").replace(tzinfo=ROME)
                results.append(await add_event(a["title"], dt))
        return "\n".join(results) if results else "Nessun evento trovato."
    except Exception:
        return "Non ho capito quale evento eliminare."


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
