import httpx
import os
import json
from datetime import datetime, timezone

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
DB_REMINDERS = "38a9d2a5-23ac-8158-badb-f41c332b13e4"
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}

STATI = ["nuova", "chiamato", "vista", "rivista", "proposta", "scartata"]
_STATI_LABEL = {
    "nuova": "🆕 nuova",
    "chiamato": "📞 chiamato",
    "vista": "👀 vista",
    "rivista": "🔁 rivista",
    "proposta": "✉️ proposta",
    "scartata": "🗑️ scartata",
}

# Normalizza le forme verbali italiane usate in chat verso lo stato canonico
_VERBO_TO_STATO = {
    "chiamato": "chiamato", "chiamata": "chiamato",
    "vista": "vista", "visto": "vista",
    "rivista": "rivista", "rivisto": "rivista",
    "proposta": "proposta", "proposto": "proposta",
    "scartata": "scartata", "scartato": "scartata", "scarta": "scartata", "scartala": "scartata",
}


def _now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _fmt_prezzo(prezzo) -> str:
    try:
        return f"€{float(prezzo):,.0f}".replace(",", ".")
    except (TypeError, ValueError):
        return "prezzo n/d"


async def add_house(via: str, comune: str, prezzo, link: str) -> str:
    payload = {"via": via, "comune": comune, "prezzo": prezzo, "link": link, "stato": "nuova"}
    async with httpx.AsyncClient(timeout=10) as client:
        await client.post("https://api.notion.com/v1/pages", headers=HEADERS, json={
            "parent": {"database_id": DB_REMINDERS},
            "properties": {
                "text": {"title": [{"text": {"content": f"CASA:{json.dumps(payload, ensure_ascii=False)}"}}]},
                "remind_at": {"date": {"start": _now_str()}},
                "sent": {"checkbox": False},
            }
        })
    return (f"🏠 Aggiunta *{via}* ({comune}) — {_fmt_prezzo(prezzo)}\n{link}\n\n"
            f"Se qualcosa è sbagliato, scrivimelo pure e la sistemo.")


async def _get_houses() -> list[dict]:
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(f"https://api.notion.com/v1/databases/{DB_REMINDERS}/query",
            headers=HEADERS, json={
                "filter": {"property": "text", "title": {"starts_with": "CASA:"}},
                "page_size": 100,
            })
    results = []
    for p in r.json().get("results", []):
        text_parts = p["properties"].get("text", {}).get("title", [])
        text = text_parts[0]["plain_text"] if text_parts else ""
        if not text.startswith("CASA:"):
            continue
        try:
            payload = json.loads(text[len("CASA:"):])
        except Exception:
            continue
        results.append({"id": p["id"], **payload})
    return results


async def update_house_status(via_query: str, stato_verbo: str) -> str | None:
    """Trova la casa per via (fuzzy, case-insensitive) e aggiorna lo stato. None se non trovata."""
    new_stato = _VERBO_TO_STATO.get(stato_verbo.lower())
    if not new_stato:
        return None
    houses = await _get_houses()
    q = via_query.lower().strip()
    match = next((h for h in houses if q in h["via"].lower() or h["via"].lower() in q), None)
    if not match:
        return None
    payload = {**{k: match[k] for k in ("via", "comune", "prezzo", "link")}, "stato": new_stato}
    async with httpx.AsyncClient(timeout=10) as client:
        await client.patch(f"https://api.notion.com/v1/pages/{match['id']}", headers=HEADERS, json={
            "properties": {
                "text": {"title": [{"text": {"content": f"CASA:{json.dumps(payload, ensure_ascii=False)}"}}]},
            }
        })
    return f"🏠 *{match['via']}* → {_STATI_LABEL[new_stato]}"


def format_houses(houses: list[dict], scartate: bool = False) -> str:
    filtered = [h for h in houses if (h.get("stato") == "scartata") == scartate]
    if not filtered:
        return "🏠 Nessuna casa scartata." if scartate else "🏠 Nessuna casa in lista al momento."
    title = "🏠 *Case scartate:*\n\n" if scartate else "🏠 *Case in lista:*\n\n"
    lines = [title]
    for h in filtered:
        stato_label = _STATI_LABEL.get(h.get("stato"), h.get("stato", "?"))
        lines.append(f"• *{h['via']}* ({h['comune']}) — {_fmt_prezzo(h.get('prezzo'))} — {stato_label}\n  {h['link']}")
    return "\n".join(lines)


async def list_houses(scartate: bool = False) -> str:
    houses = await _get_houses()
    return format_houses(houses, scartate)
