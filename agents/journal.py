import httpx
import os
from datetime import datetime, date

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
DB_JOURNAL = "fba0b243-ec31-40b3-b306-37e075e88966"
STREAK_ANCHOR = date(2026, 7, 2)

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}


async def add_journal_entry(text: str, cedimento: bool = False) -> str:
    """Salva una entry di diario (testo libero) o un cedimento (resetta lo streak)."""
    today = date.today()
    body = {
        "parent": {"database_id": DB_JOURNAL},
        "properties": {
            "Name": {"title": [{"text": {"content": today.isoformat()}}]},
            "text": {"rich_text": [{"text": {"content": text}}]},
            "date": {"date": {"start": today.isoformat()}},
            "cedimento": {"checkbox": cedimento},
        },
    }
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post("https://api.notion.com/v1/pages", headers=HEADERS, json=body)
    if r.status_code != 200:
        return f"Errore salvataggio diario: {r.status_code}"
    if cedimento:
        return "💙 Segnato. Streak resettato — si riparte da domani, giorno 1."
    return "📓 Entry salvata."


async def _get_last_relapse_date() -> date | None:
    body = {
        "filter": {"property": "cedimento", "checkbox": {"equals": True}},
        "sorts": [{"property": "date", "direction": "descending"}],
        "page_size": 1,
    }
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(f"https://api.notion.com/v1/databases/{DB_JOURNAL}/query", headers=HEADERS, json=body)
    results = r.json().get("results", [])
    if not results:
        return None
    date_iso = (results[0]["properties"].get("date", {}).get("date") or {}).get("start", "")[:10]
    return date.fromisoformat(date_iso) if date_iso else None


async def get_streak_days() -> int:
    """Giorni trascorsi dall'ultimo cedimento (o dall'ancora iniziale se non ce n'è mai stato uno)."""
    last_relapse = await _get_last_relapse_date() or STREAK_ANCHOR
    return (date.today() - last_relapse).days


def format_streak_message(days: int) -> str:
    return f"💪 Giorno {days} senza cedere. Continua così!"
