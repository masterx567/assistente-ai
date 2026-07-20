import httpx
import os
import json
from datetime import datetime, timezone

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
TRACK17_API_KEY = os.getenv("TRACK17_API_KEY")
DB_REMINDERS = "38a9d2a5-23ac-8158-badb-f41c332b13e4"
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}
T17_HEADERS = {
    "17token": TRACK17_API_KEY or "",
    "Content-Type": "application/json",
}

_STATUS_IT = {
    "NotFound": "non trovato",
    "InfoReceived": "info ricevute",
    "InTransit": "in transito",
    "Expired": "scaduto",
    "AvailableForPickup": "pronto per il ritiro",
    "OutForDelivery": "in consegna",
    "DeliveryFailure": "consegna fallita",
    "Delivered": "consegnato",
    "Exception": "anomalia",
}
_TERMINAL = {"Delivered", "DeliveryFailure", "Expired", "Exception"}


def _now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


async def track_package(number: str, label: str = "") -> str:
    """Registra un tracking number su 17track e lo salva su Notion (riusa DB Reminders, prefix PACCO:)."""
    if not TRACK17_API_KEY:
        return "⚠️ Tracking non configurato (manca TRACK17_API_KEY)."
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post("https://api.17track.net/track/v2.2/register",
            headers=T17_HEADERS, json=[{"number": number}])
    data = r.json().get("data", {})
    if data.get("rejected"):
        reason = data["rejected"][0].get("error", {}).get("message", "motivo sconosciuto")
        return f"❌ Non sono riuscito a registrare il pacco: {reason}"

    payload = {"number": number, "label": label, "status": "InfoReceived"}
    async with httpx.AsyncClient(timeout=10) as client:
        await client.post("https://api.notion.com/v1/pages", headers=HEADERS, json={
            "parent": {"database_id": DB_REMINDERS},
            "properties": {
                "text": {"title": [{"text": {"content": f"PACCO:{json.dumps(payload, ensure_ascii=False)}"}}]},
                "remind_at": {"date": {"start": _now_str()}},
                "sent": {"checkbox": False},
            }
        })
    label_str = f" ({label})" if label else ""
    return f"📦 Sto tracciando il pacco {number}{label_str}. Ti avviso quando cambia stato."


async def _get_active_packages() -> list[dict]:
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(f"https://api.notion.com/v1/databases/{DB_REMINDERS}/query",
            headers=HEADERS, json={
                "filter": {"and": [
                    {"property": "sent", "checkbox": {"equals": False}},
                    {"property": "text", "title": {"starts_with": "PACCO:"}},
                ]},
                "page_size": 40,
            })
    results = []
    for p in r.json().get("results", []):
        text_parts = p["properties"].get("text", {}).get("title", [])
        text = text_parts[0]["plain_text"] if text_parts else ""
        if not text.startswith("PACCO:"):
            continue
        try:
            payload = json.loads(text[len("PACCO:"):])
        except Exception:
            continue
        results.append({"id": p["id"], **payload})
    return results


async def _update_package(page_id: str, payload: dict, delivered: bool = False):
    async with httpx.AsyncClient(timeout=10) as client:
        await client.patch(f"https://api.notion.com/v1/pages/{page_id}", headers=HEADERS, json={
            "properties": {
                "text": {"title": [{"text": {"content": f"PACCO:{json.dumps(payload, ensure_ascii=False)}"}}]},
                "remind_at": {"date": {"start": _now_str()}},
                "sent": {"checkbox": delivered},
            }
        })


async def check_all_packages() -> list[str]:
    """Interroga 17track per tutti i pacchi attivi, aggiorna Notion sui cambi di stato,
    ritorna i messaggi da notificare (solo se lo stato è cambiato dall'ultimo check)."""
    if not TRACK17_API_KEY:
        return []
    packages = await _get_active_packages()
    if not packages:
        return []
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post("https://api.17track.net/track/v2.2/gettrackinfo",
            headers=T17_HEADERS, json=[{"number": p["number"]} for p in packages])
    accepted = r.json().get("data", {}).get("accepted", [])
    by_number = {a["number"]: a for a in accepted}

    notifications = []
    for pkg in packages:
        info = by_number.get(pkg["number"])
        if not info:
            continue
        new_status = info.get("track_info", {}).get("latest_status", {}).get("status", "")
        if new_status and new_status != pkg.get("status"):
            label_str = f" ({pkg['label']})" if pkg.get("label") else ""
            status_it = _STATUS_IT.get(new_status, new_status)
            notifications.append(f"📦 Pacco {pkg['number']}{label_str}: *{status_it}*")
            await _update_package(
                pkg["id"],
                {"number": pkg["number"], "label": pkg.get("label", ""), "status": new_status},
                delivered=new_status in _TERMINAL,
            )
    return notifications


async def list_packages() -> str:
    packages = await _get_active_packages()
    if not packages:
        return "📦 Nessun pacco in tracking al momento."
    lines = ["📦 *Pacchi in tracking:*\n"]
    for p in packages:
        label_str = f" ({p['label']})" if p.get("label") else ""
        status_it = _STATUS_IT.get(p.get("status", ""), p.get("status", "sconosciuto"))
        lines.append(f"• {p['number']}{label_str} — {status_it}")
    return "\n".join(lines)
