import httpx
import os
from agents.budget import get_monthly_spending, get_budget_alerts, format_spending_summary, format_alerts
from agents.news import get_morning_briefing

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

SYSTEM_PROMPT = """Sei un assistente finanziario e personale italiano. Rispondi sempre in italiano.
Sei conciso, utile e diretto. Usi emoji appropriati.

Puoi fare queste cose:
- Mostrare spese del mese corrente per categoria
- Avvisare su budget quasi esauriti o superati
- Dare notizie del giorno
- Rispondere a domande generali

Quando ricevi dati strutturati (spese, alert), formattali in modo chiaro e leggibile per Telegram (usa *grassetto* e • per liste).
"""


async def route_message(user_text: str) -> str:
    """Capisce l'intento dell'utente e risponde."""
    text_lower = user_text.lower()

    # Budget / spese
    if any(w in text_lower for w in ["spes", "budget", "quanto", "soldi", "spendo", "categor", "mese"]):
        spending = await get_monthly_spending()
        alerts = await get_budget_alerts()
        context = format_spending_summary(spending)
        if alerts:
            context += "\n\n" + format_alerts(alerts)
        return await ask_groq(user_text, context)

    # Notizie
    if any(w in text_lower for w in ["notizi", "news", "oggi", "succede", "aggiornament", "giornale"]):
        briefing = await get_morning_briefing()
        return briefing

    # Default: risposta generica
    return await ask_groq(user_text, "")


async def ask_groq(user_text: str, context: str = "") -> str:
    """Chiama Groq (Llama 3.3 70B) per generare una risposta."""
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
