import httpx
import os
from datetime import datetime, timezone

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
DB_REMINDERS = "38a9d2a5-23ac-8158-badb-f41c332b13e4"
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}


async def save_pending(action: str, payload: dict) -> str:
    """Salva azione pending in Notion (riusa Reminders DB con text = JSON)."""
    import json
    text = f"PENDING:{action}:{json.dumps(payload, ensure_ascii=False)}"
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post("https://api.notion.com/v1/pages", headers=HEADERS, json={
            "parent": {"database_id": DB_REMINDERS},
            "properties": {
                "text": {"title": [{"text": {"content": text}}]},
                "remind_at": {"date": {"start": now_str}},
                "sent": {"checkbox": False},
            }
        })
    return r.json().get("id", "")


async def get_pending() -> dict | None:
    """Recupera l'ultima azione pending non confermata."""
    import json
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(f"https://api.notion.com/v1/databases/{DB_REMINDERS}/query",
            headers=HEADERS, json={
                "filter": {"property": "sent", "checkbox": {"equals": False}},
                "sorts": [{"property": "remind_at", "direction": "descending"}],
                "page_size": 5,
            })
    for p in r.json().get("results", []):
        text_parts = p["properties"].get("text", {}).get("title", [])
        text = text_parts[0]["plain_text"] if text_parts else ""
        if text.startswith("PENDING:"):
            parts = text.split(":", 2)
            if len(parts) == 3:
                try:
                    payload = json.loads(parts[2])
                    return {"id": p["id"], "action": parts[1], "payload": payload}
                except Exception:
                    pass
    return None


async def clear_pending(page_id: str):
    async with httpx.AsyncClient(timeout=10) as client:
        await client.patch(f"https://api.notion.com/v1/pages/{page_id}",
            headers=HEADERS, json={"properties": {"sent": {"checkbox": True}}})


async def already_ticked(key: str) -> bool:
    """Controlla se un'azione tick (identificata da key, es. 'evening:2026-07-02') è già stata eseguita.
    Serve a deduplicare invii doppi/tripli se cron-job.org ritenta la chiamata su timeout."""
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(f"https://api.notion.com/v1/databases/{DB_REMINDERS}/query",
            headers=HEADERS, json={
                "filter": {"property": "text", "title": {"equals": f"TICKLOCK:{key}"}},
                "page_size": 1,
            })
    return bool(r.json().get("results"))


async def mark_ticked(key: str):
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    async with httpx.AsyncClient(timeout=10) as client:
        await client.post("https://api.notion.com/v1/pages", headers=HEADERS, json={
            "parent": {"database_id": DB_REMINDERS},
            "properties": {
                "text": {"title": [{"text": {"content": f"TICKLOCK:{key}"}}]},
                "remind_at": {"date": {"start": now_str}},
                "sent": {"checkbox": True},
            }
        })
