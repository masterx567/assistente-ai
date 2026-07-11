import httpx
import os
import calendar as _calendar
from datetime import datetime, date, timedelta

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
DB_JOURNAL = "fba0b243-ec31-40b3-b306-37e075e88966"

_MONTHS_IT = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4,
    "maggio": 5, "giugno": 6, "luglio": 7, "agosto": 8,
    "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
}

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}


async def add_journal_entry(text: str) -> str:
    """Salva una entry di diario (testo libero)."""
    today = date.today()
    body = {
        "parent": {"database_id": DB_JOURNAL},
        "properties": {
            "Name": {"title": [{"text": {"content": today.isoformat()}}]},
            "text": {"rich_text": [{"text": {"content": text}}]},
            "date": {"date": {"start": today.isoformat()}},
        },
    }
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post("https://api.notion.com/v1/pages", headers=HEADERS, json=body)
    if r.status_code != 200:
        return f"Errore salvataggio diario: {r.status_code}"
    return "📓 Entry salvata."


def _period_to_range(period: str) -> tuple[date, date]:
    today = date.today()
    period_l = period.lower().strip()
    if "settimana" in period_l:
        return today - timedelta(days=7), today
    matched_month = next((num for name, num in _MONTHS_IT.items() if name in period_l), None)
    if matched_month:
        year = today.year if matched_month <= today.month else today.year - 1
        last_day = _calendar.monthrange(year, matched_month)[1]
        return date(year, matched_month, 1), date(year, matched_month, last_day)
    return date(today.year, today.month, 1), today


async def get_journal_entries(period: str) -> tuple[list[dict], date, date]:
    """Entry diario (e cedimenti) in un periodo, ordinate cronologicamente."""
    start, end = _period_to_range(period)
    body = {
        "filter": {"and": [
            {"property": "date", "date": {"on_or_after": start.isoformat()}},
            {"property": "date", "date": {"on_or_before": end.isoformat()}},
        ]},
        "sorts": [{"property": "date", "direction": "ascending"}],
        "page_size": 100,
    }
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(f"https://api.notion.com/v1/databases/{DB_JOURNAL}/query", headers=HEADERS, json=body)
    entries = []
    for page in r.json().get("results", []):
        props = page["properties"]
        text_parts = props.get("text", {}).get("rich_text", [])
        text = text_parts[0]["plain_text"] if text_parts else ""
        date_iso = (props.get("date", {}).get("date") or {}).get("start", "")[:10]
        cedimento = props.get("cedimento", {}).get("checkbox", False)
        entries.append({"date": date_iso, "text": text, "cedimento": cedimento})
    return entries, start, end


def format_journal_entries(entries: list[dict], start: date, end: date) -> str:
    if not entries:
        return f"Nessuna entry nel diario tra {start.strftime('%d/%m')} e {end.strftime('%d/%m/%Y')}."
    lines = [f"📔 *Diario ({start.strftime('%d/%m')} – {end.strftime('%d/%m/%Y')})*\n"]
    for e in entries:
        emoji = "💙" if e["cedimento"] else "📓"
        d = datetime.fromisoformat(e["date"]).strftime("%d/%m") if e["date"] else "?"
        lines.append(f"{emoji} *{d}* — {e['text']}")
    return "\n".join(lines)
