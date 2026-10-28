"""Backend della dashboard casa (casa-three-phi.vercel.app).
Legge/scrive il DB Notion CasaItems e sincronizza scadenze/task sul Google Calendar.
Vive qui per riusare NOTION_TOKEN e le credenziali Google del bot."""
import os
import asyncio
from datetime import date, timedelta
import httpx

from agents.calendar import _get_access_token

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
CASA_DB = os.getenv("CASA_DB", "a5bf6e4ff70446a8b6c1145bc06b41df")
CASA_INVITE = [e for e in os.getenv("CASA_INVITE", "").split(",") if e]
CAL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}


def _txt(p) -> str:
    if not p:
        return ""
    return "".join(t.get("plain_text", "") for t in (p.get("rich_text") or p.get("title") or []))


def _row(pg: dict) -> dict:
    P = pg["properties"]
    sel = lambda k: (P.get(k) or {}).get("select") and P[k]["select"]["name"]
    return {
        "id": pg["id"],
        "nome": _txt(P.get("Nome")),
        "tipo": sel("Tipo") or None,
        "fase": sel("Fase") or None,
        "data": ((P.get("Data") or {}).get("date") or {}).get("start"),
        "chi": sel("Chi") or None,
        "fatto": bool((P.get("Fatto") or {}).get("checkbox")),
        "importo": (P.get("Importo") or {}).get("number"),
        "note": _txt(P.get("Note")),
        "telefono": (P.get("Telefono") or {}).get("phone_number"),
        "calId": _txt(P.get("CalId")),
    }


async def casa_list() -> list[dict]:
    out, cursor = [], None
    async with httpx.AsyncClient(timeout=8) as c:
        while True:
            body = {"start_cursor": cursor} if cursor else {}
            r = (await c.post(f"https://api.notion.com/v1/databases/{CASA_DB}/query", headers=HEADERS, json=body)).json()
            if "results" not in r:
                raise RuntimeError(r.get("message", "notion error"))
            out += [_row(p) for p in r["results"]]
            if not r.get("has_more"):
                return out
            cursor = r["next_cursor"]


async def casa_update(page_id: str, data: dict):
    props = {}
    if isinstance(data.get("fatto"), bool):
        props["Fatto"] = {"checkbox": data["fatto"]}
    if isinstance(data.get("importo"), (int, float)) and not isinstance(data.get("importo"), bool):
        props["Importo"] = {"number": data["importo"]}
    if data.get("fase"):
        props["Fase"] = {"select": {"name": data["fase"]}}
    if "data" in data:
        props["Data"] = {"date": {"start": data["data"]} if data["data"] else None}
    async with httpx.AsyncClient(timeout=8) as c:
        r = await c.patch(f"https://api.notion.com/v1/pages/{page_id}", headers=HEADERS, json={"properties": props})
    if r.status_code >= 300:
        raise RuntimeError(r.text[:200])


def _event(i: dict) -> dict:
    end = date.fromisoformat(i["data"][:10]) + timedelta(days=1)
    return {
        "summary": f"{'✅' if i['fatto'] else '🏠'} {i['nome']}" + (f" ({i['chi']})" if i["chi"] else ""),
        "description": i["note"],
        "start": {"date": i["data"][:10]},
        "end": {"date": end.isoformat()},
        "attendees": [{"email": e} for e in CASA_INVITE],
        "reminders": {"useDefault": False, "overrides": [
            {"method": "popup", "minutes": 3 * 24 * 60}, {"method": "popup", "minutes": 9 * 60}]},
    }


async def casa_sync() -> int:
    """Scadenze/Task con data -> Calendar. Crea (salvando CalId su Notion) o aggiorna. In parallelo per stare nei 10s Vercel."""
    token = await _get_access_token()
    if not token:
        raise RuntimeError("Google Calendar non configurato")
    items = [i for i in await casa_list() if i["tipo"] in ("Scadenza", "Task") and i["data"]]
    gh = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient(timeout=8) as c:
        async def one(i):
            if i["calId"]:
                await c.patch(f"{CAL}/{i['calId']}", params={"sendUpdates": "none"}, headers=gh, json=_event(i))
                return
            r = (await c.post(CAL, params={"sendUpdates": "all"}, headers=gh, json=_event(i))).json()
            if "id" in r:
                await c.patch(f"https://api.notion.com/v1/pages/{i['id']}", headers=HEADERS, json={
                    "properties": {"CalId": {"rich_text": [{"text": {"content": r["id"]}}]}}})

        await asyncio.gather(*(one(i) for i in items))
    return len(items)
