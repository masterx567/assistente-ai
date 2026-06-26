import httpx
import os
from datetime import datetime, timezone

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
DB_ERRORS = "38b9d2a5-23ac-81f5-935c-c9b665d4330f"
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}


def log_error(error: str, user_input: str = "", traceback: str = ""):
    """Logga un errore su Notion BotErrors (sync, fire-and-forget)."""
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    try:
        httpx.post("https://api.notion.com/v1/pages", headers=HEADERS, json={
            "parent": {"database_id": DB_ERRORS},
            "properties": {
                "error": {"title": [{"text": {"content": error[:200]}}]},
                "input": {"rich_text": [{"text": {"content": user_input[:500]}}]},
                "traceback": {"rich_text": [{"text": {"content": traceback[:2000]}}]},
                "timestamp": {"date": {"start": now_str}},
                "resolved": {"checkbox": False},
            }
        }, timeout=5)
    except Exception:
        pass


async def get_unresolved_errors() -> list[dict]:
    """Ritorna errori non risolti."""
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(f"https://api.notion.com/v1/databases/{DB_ERRORS}/query",
            headers=HEADERS, json={
                "filter": {"property": "resolved", "checkbox": {"equals": False}},
                "sorts": [{"property": "timestamp", "direction": "descending"}],
                "page_size": 20,
            })
    results = []
    for p in r.json().get("results", []):
        props = p["properties"]
        error = (props.get("error", {}).get("title", [{}]) or [{}])[0].get("plain_text", "")
        inp = (props.get("input", {}).get("rich_text", [{}]) or [{}])[0].get("plain_text", "")
        tb = (props.get("traceback", {}).get("rich_text", [{}]) or [{}])[0].get("plain_text", "")
        ts = (props.get("timestamp", {}).get("date") or {}).get("start", "")
        results.append({"id": p["id"], "error": error, "input": inp, "traceback": tb, "timestamp": ts})
    return results


def mark_resolved(page_id: str):
    try:
        httpx.patch(f"https://api.notion.com/v1/pages/{page_id}", headers=HEADERS,
            json={"properties": {"resolved": {"checkbox": True}}}, timeout=5)
    except Exception:
        pass
