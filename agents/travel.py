import httpx
import os
from datetime import date

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
DB_VIAGGI = "db4354c9-938d-4d89-99e8-4047be81b84b"
DB_CHECKLIST = "389b5abc-34d6-4804-b9da-1b188f2d4402"

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}

DEFAULT_CHECKLIST = [
    "Documento identità/passaporto", "Caricabatterie", "Power bank",
    "Adattatore presa", "Farmaci personali", "Spazzolino e dentifricio",
    "Cuffie", "Contanti/carta",
]


async def create_trip(destinazione: str, start_iso: str, end_iso: str, budget: float) -> str:
    """Crea il viaggio + checklist di default. Ritorna l'id del viaggio."""
    body = {
        "parent": {"database_id": DB_VIAGGI},
        "properties": {
            "Name": {"title": [{"text": {"content": destinazione}}]},
            "data_inizio": {"date": {"start": start_iso}},
            "data_fine": {"date": {"start": end_iso}},
            "budget": {"number": budget},
        },
    }
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post("https://api.notion.com/v1/pages", headers=HEADERS, json=body)
    trip_id = r.json()["id"]

    async with httpx.AsyncClient(timeout=15) as client:
        for item in DEFAULT_CHECKLIST:
            await client.post("https://api.notion.com/v1/pages", headers=HEADERS, json={
                "parent": {"database_id": DB_CHECKLIST},
                "properties": {
                    "Name": {"title": [{"text": {"content": item}}]},
                    "viaggio": {"relation": [{"id": trip_id}]},
                    "fatto": {"checkbox": False},
                },
            })
    return trip_id


async def get_active_trip() -> dict | None:
    """Viaggio in corso, o il prossimo futuro se nessuno è in corso."""
    today = date.today().isoformat()
    body = {
        "filter": {"property": "data_fine", "date": {"on_or_after": today}},
        "sorts": [{"property": "data_inizio", "direction": "ascending"}],
        "page_size": 1,
    }
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(f"https://api.notion.com/v1/databases/{DB_VIAGGI}/query", headers=HEADERS, json=body)
    results = r.json().get("results", [])
    if not results:
        return None
    page = results[0]
    props = page["properties"]
    name_parts = props.get("Name", {}).get("title", [])
    name = name_parts[0]["plain_text"] if name_parts else "?"
    start = (props.get("data_inizio", {}).get("date") or {}).get("start", "")[:10]
    end = (props.get("data_fine", {}).get("date") or {}).get("start", "")[:10]
    budget = props.get("budget", {}).get("number") or 0
    return {"id": page["id"], "destinazione": name, "start": start, "end": end, "budget": budget}


async def delete_trip(trip_id: str) -> None:
    """Archivia il viaggio e tutte le sue voci checklist."""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(f"https://api.notion.com/v1/databases/{DB_CHECKLIST}/query", headers=HEADERS, json={
            "filter": {"property": "viaggio", "relation": {"contains": trip_id}},
            "page_size": 50,
        })
        for page in r.json().get("results", []):
            await client.patch(f"https://api.notion.com/v1/pages/{page['id']}", headers=HEADERS, json={"archived": True})
        await client.patch(f"https://api.notion.com/v1/pages/{trip_id}", headers=HEADERS, json={"archived": True})


async def get_trip_spending(trip: dict) -> float:
    """Somma le spese sincronizzate (source=api) nel periodo del viaggio."""
    from agents.enable_banking import DB_TRANSACTIONS, NOTION_HEADERS
    body = {
        "filter": {"and": [
            {"property": "source", "select": {"equals": "api"}},
            {"property": "date", "date": {"on_or_after": trip["start"]}},
            {"property": "date", "date": {"on_or_before": trip["end"]}},
            {"property": "amount", "number": {"less_than": 0}},
        ]},
        "page_size": 100,
    }
    total = 0.0
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(f"https://api.notion.com/v1/databases/{DB_TRANSACTIONS}/query", headers=NOTION_HEADERS, json=body)
    for page in r.json().get("results", []):
        total += abs(page["properties"].get("amount", {}).get("number") or 0)
    return total


def format_trip_budget(trip: dict, spent: float) -> str:
    remaining = trip["budget"] - spent
    pct = (spent / trip["budget"] * 100) if trip["budget"] > 0 else 0
    emoji = "🟢" if pct < 80 else ("⚠️" if pct < 100 else "🚨")
    start_fmt = date.fromisoformat(trip["start"]).strftime("%d/%m")
    end_fmt = date.fromisoformat(trip["end"]).strftime("%d/%m")
    return (
        f"✈️ *{trip['destinazione']}* ({start_fmt}–{end_fmt})\n"
        f"{emoji} €{spent:.0f}/€{trip['budget']:.0f} speso ({pct:.0f}%)\n"
        f"Ti restano *€{remaining:.0f}*"
    )


async def get_trip_transactions(trip: dict) -> list[dict]:
    """Transazioni sincronizzate (source=api) nel periodo del viaggio, con id per poterle eliminare."""
    from agents.enable_banking import DB_TRANSACTIONS, NOTION_HEADERS
    body = {
        "filter": {"and": [
            {"property": "source", "select": {"equals": "api"}},
            {"property": "date", "date": {"on_or_after": trip["start"]}},
            {"property": "date", "date": {"on_or_before": trip["end"]}},
            {"property": "amount", "number": {"less_than": 0}},
        ]},
        "sorts": [{"property": "date", "direction": "descending"}],
        "page_size": 50,
    }
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(f"https://api.notion.com/v1/databases/{DB_TRANSACTIONS}/query", headers=NOTION_HEADERS, json=body)
    results = []
    for page in r.json().get("results", []):
        props = page["properties"]
        amount = abs(props.get("amount", {}).get("number") or 0)
        merchant_parts = props.get("merchant_raw", {}).get("rich_text", [])
        merchant = merchant_parts[0]["plain_text"] if merchant_parts else "?"
        date_str = (props.get("date", {}).get("date") or {}).get("start", "")[:10]
        results.append({"id": page["id"], "merchant": merchant, "amount": amount, "date": date_str})
    return results


def trip_transactions_buttons(transactions: list[dict]) -> dict:
    """Tastiera inline: una transazione per riga, tap = elimina. callback_data = 'td:{tx_id}'."""
    rows = []
    for t in transactions:
        d = date.fromisoformat(t["date"]).strftime("%d/%m") if t["date"] else "?"
        rows.append([{"text": f"🗑️ {d} {t['merchant']} -€{t['amount']:.2f}", "callback_data": f"td:{t['id']}"}])
    return {"inline_keyboard": rows}


async def delete_trip_transaction(tx_id: str) -> None:
    from agents.enable_banking import NOTION_HEADERS
    async with httpx.AsyncClient(timeout=10) as client:
        await client.patch(f"https://api.notion.com/v1/pages/{tx_id}", headers=NOTION_HEADERS, json={"archived": True})


async def get_checklist(trip_id: str) -> list[dict]:
    body = {
        "filter": {"property": "viaggio", "relation": {"contains": trip_id}},
        "page_size": 50,
    }
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(f"https://api.notion.com/v1/databases/{DB_CHECKLIST}/query", headers=HEADERS, json=body)
    items = []
    for page in r.json().get("results", []):
        props = page["properties"]
        name_parts = props.get("Name", {}).get("title", [])
        name = name_parts[0]["plain_text"] if name_parts else "?"
        fatto = props.get("fatto", {}).get("checkbox", False)
        items.append({"id": page["id"], "testo": name, "fatto": fatto})
    return items


def format_checklist(items: list[dict]) -> str:
    if not items:
        return "Nessuna checklist per questo viaggio."
    done = sum(1 for i in items if i["fatto"])
    return f"🧳 *Checklist* ({done}/{len(items)}) — tocca una voce per spuntarla:"


def checklist_buttons(items: list[dict]) -> dict:
    """Tastiera inline, una voce per riga, callback_data = 'cl:{item_id}'."""
    rows = []
    for i in items:
        emoji = "✅" if i["fatto"] else "⬜"
        rows.append([{"text": f"{emoji} {i['testo']}", "callback_data": f"cl:{i['id']}"}])
    return {"inline_keyboard": rows}


async def toggle_checklist_item(item_id: str) -> bool:
    """Inverte lo stato fatto/non-fatto di una voce. Ritorna il nuovo stato."""
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"https://api.notion.com/v1/pages/{item_id}", headers=HEADERS)
        current = r.json()["properties"].get("fatto", {}).get("checkbox", False)
        new_state = not current
        await client.patch(f"https://api.notion.com/v1/pages/{item_id}", headers=HEADERS, json={
            "properties": {"fatto": {"checkbox": new_state}}
        })
    return new_state


async def get_checklist_by_trip_of_item(item_id: str) -> str | None:
    """Ritorna il trip_id a cui appartiene una voce checklist (per rigenerare la tastiera dopo il tap)."""
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"https://api.notion.com/v1/pages/{item_id}", headers=HEADERS)
    rel = r.json()["properties"].get("viaggio", {}).get("relation", [])
    return rel[0]["id"] if rel else None


async def mark_checklist_item(trip_id: str, query: str) -> str | None:
    """Segna come fatta la voce che matcha meglio query. Ritorna il testo trovato o None."""
    items = await get_checklist(trip_id)
    query_l = query.lower().strip()
    match = next((i for i in items if query_l in i["testo"].lower() or i["testo"].lower() in query_l), None)
    if not match:
        return None
    async with httpx.AsyncClient(timeout=10) as client:
        await client.patch(f"https://api.notion.com/v1/pages/{match['id']}", headers=HEADERS, json={
            "properties": {"fatto": {"checkbox": True}}
        })
    return match["testo"]


async def delete_checklist_item(trip_id: str, query: str) -> str | None:
    """Elimina (archivia) la voce che matcha meglio query. Ritorna il testo trovato o None."""
    items = await get_checklist(trip_id)
    query_l = query.lower().strip()
    match = next((i for i in items if query_l in i["testo"].lower() or i["testo"].lower() in query_l), None)
    if not match:
        return None
    async with httpx.AsyncClient(timeout=10) as client:
        await client.patch(f"https://api.notion.com/v1/pages/{match['id']}", headers=HEADERS, json={"archived": True})
    return match["testo"]


async def add_checklist_item(trip_id: str, testo: str) -> None:
    async with httpx.AsyncClient(timeout=10) as client:
        await client.post("https://api.notion.com/v1/pages", headers=HEADERS, json={
            "parent": {"database_id": DB_CHECKLIST},
            "properties": {
                "Name": {"title": [{"text": {"content": testo}}]},
                "viaggio": {"relation": [{"id": trip_id}]},
                "fatto": {"checkbox": False},
            },
        })
