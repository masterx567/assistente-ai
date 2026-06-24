import httpx
import os
from agents.news import get_morning_briefing
from agents.budget import get_budget_alerts, format_alerts

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


async def send_telegram(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    async with httpx.AsyncClient() as client:
        await client.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "Markdown",
        })


async def morning_briefing_job():
    """Ogni mattina alle 8:00 — notizie del giorno."""
    briefing = await get_morning_briefing()
    await send_telegram(f"☀️ *Buongiorno!*\n\n{briefing}")


async def budget_check_job():
    """Ogni giorno alle 20:00 — controlla budget."""
    alerts = await get_budget_alerts()
    if not alerts:
        return
    msg = "💳 *Aggiornamento Budget*\n\n" + format_alerts(alerts)
    await send_telegram(msg)
