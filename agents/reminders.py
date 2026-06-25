import httpx
import os
from datetime import datetime
from zoneinfo import ZoneInfo

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
DB_REMINDERS = "38a9d2a5-23ac-8158-badb-f41c332b13e4"
ROME = ZoneInfo("Europe/Rome")
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}


async def add_reminder(text: str, remind_at: datetime) -> str:
    dt_str = remind_at.strftime("%Y-%m-%dT%H:%M:%S+02:00")
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post("https://api.notion.com/v1/pages", headers=HEADERS, json={
            "parent": {"database_id": DB_REMINDERS},
            "properties": {
                "text": {"title": [{"text": {"content": text}}]},
                "remind_at": {"date": {"start": dt_str}},
                "sent": {"checkbox": False},
            }
        })
    if r.status_code == 200:
        return f"🔔 Promemoria salvato per {remind_at.strftime('%d/%m alle %H:%M')}"
    return f"Errore salvataggio promemoria: {r.status_code}"


async def get_pending_reminders(now: datetime) -> list[dict]:
    """Ritorna promemoria non inviati con remind_at <= now."""
    now_str = now.strftime("%Y-%m-%dT%H:%M:%S+02:00")
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(f"https://api.notion.com/v1/databases/{DB_REMINDERS}/query",
            headers=HEADERS, json={
                "filter": {"and": [
                    {"property": "sent", "checkbox": {"equals": False}},
                    {"property": "remind_at", "date": {"on_or_before": now_str}},
                ]},
                "page_size": 20,
            })
    results = []
    for p in r.json().get("results", []):
        text_parts = p["properties"].get("text", {}).get("title", [])
        text = text_parts[0]["plain_text"] if text_parts else ""
        results.append({"id": p["id"], "text": text})
    return results


async def mark_sent(page_id: str):
    async with httpx.AsyncClient(timeout=10) as client:
        await client.patch(f"https://api.notion.com/v1/pages/{page_id}",
            headers=HEADERS, json={"properties": {"sent": {"checkbox": True}}})
