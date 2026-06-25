import httpx
from datetime import datetime, timedelta
import os

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
DB_TRANSACTIONS = os.getenv("NOTION_DB_TRANSACTIONS")
DB_CATEGORIES = os.getenv("NOTION_DB_CATEGORIES")
DB_MERCHANTMAP = "c82a1f2a-a1dc-421b-aeb8-e0fc4e413354"

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}


async def _get_all_category_names() -> dict[str, str]:
    """Ritorna dict {category_page_id: name} con una sola chiamata."""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(
            f"https://api.notion.com/v1/databases/{DB_CATEGORIES}/query",
            headers=HEADERS, json={"page_size": 100}
        )
    result = {}
    for c in r.json().get("results", []):
        name_parts = c["properties"].get("Name", {}).get("title", [])
        name = name_parts[0]["plain_text"] if name_parts else ""
        if name:
            result[c["id"]] = name
    return result


async def get_monthly_spending() -> dict:
    """Ritorna spese mese corrente per categoria."""
    now = datetime.now()
    start = f"{now.year}-{now.month:02d}-01"
    end = f"{now.year}-{now.month:02d}-{_last_day(now.year, now.month):02d}"

    cat_names = await _get_all_category_names()

    body = {
        "filter": {
            "and": [
                {"property": "date", "date": {"on_or_after": start}},
                {"property": "date", "date": {"on_or_before": end}},
                {"property": "amount", "number": {"less_than": 0}},
            ]
        },
        "page_size": 100,
    }

    transactions = []
    cursor = None
    async with httpx.AsyncClient(timeout=30) as client:
        while True:
            if cursor:
                body["start_cursor"] = cursor
            r = await client.post(
                f"https://api.notion.com/v1/databases/{DB_TRANSACTIONS}/query",
                headers=HEADERS, json=body
            )
            data = r.json()
            transactions.extend(data.get("results", []))
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")

    spending: dict[str, float] = {}
    for t in transactions:
        props = t["properties"]
        amount = props.get("amount", {}).get("number", 0) or 0
        cat_rel = props.get("category", {}).get("relation", [])
        cat_name = cat_names.get(cat_rel[0]["id"], "Senza categoria") if cat_rel else "Senza categoria"
        spending[cat_name] = spending.get(cat_name, 0) + abs(amount)

    return spending


async def get_budget_alerts() -> list[dict]:
    """Ritorna categorie che hanno superato 80% o 100% del budget."""
    spending = await get_monthly_spending()
    budgets = await get_category_budgets()
    alerts = []
    for cat, budget in budgets.items():
        if budget <= 0:
            continue
        spent = spending.get(cat, 0)
        pct = spent / budget * 100
        if pct >= 100:
            alerts.append({"category": cat, "spent": spent, "budget": budget, "pct": pct, "level": "over"})
        elif pct >= 80:
            alerts.append({"category": cat, "spent": spent, "budget": budget, "pct": pct, "level": "warning"})
    return sorted(alerts, key=lambda x: x["pct"], reverse=True)


async def get_category_budgets() -> dict[str, float]:
    """Legge budget mensile da Notion Categories."""
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"https://api.notion.com/v1/databases/{DB_CATEGORIES}/query",
            headers=HEADERS, json={"page_size": 100}
        )
    cats = r.json().get("results", [])
    budgets = {}
    for c in cats:
        props = c["properties"]
        name_parts = props.get("Name", {}).get("title", [])
        name = name_parts[0]["plain_text"] if name_parts else ""
        budget = props.get("budget_mensile", {}).get("number") or 0
        if name:
            budgets[name] = budget
    return budgets


async def _get_category_name(cat_id: str) -> str:
    async with httpx.AsyncClient() as client:
        r = await client.get(f"https://api.notion.com/v1/pages/{cat_id}", headers=HEADERS)
    props = r.json().get("properties", {})
    name_parts = props.get("Name", {}).get("title", [])
    return name_parts[0]["plain_text"] if name_parts else "Senza categoria"


def _last_day(year: int, month: int) -> int:
    import calendar
    return calendar.monthrange(year, month)[1]


async def get_weekly_spending() -> dict:
    """Spese ultimi 7 giorni per categoria."""
    now = datetime.now()
    start = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    end = now.strftime("%Y-%m-%d")
    cat_names = await _get_all_category_names()
    body = {
        "filter": {"and": [
            {"property": "date", "date": {"on_or_after": start}},
            {"property": "date", "date": {"on_or_before": end}},
            {"property": "amount", "number": {"less_than": 0}},
        ]},
        "page_size": 100,
    }
    transactions = []
    async with httpx.AsyncClient(timeout=30) as client:
        while True:
            r = await client.post(f"https://api.notion.com/v1/databases/{DB_TRANSACTIONS}/query", headers=HEADERS, json=body)
            data = r.json()
            transactions.extend(data.get("results", []))
            if not data.get("has_more"):
                break
            body["start_cursor"] = data["next_cursor"]
    spending: dict[str, float] = {}
    for t in transactions:
        props = t["properties"]
        amount = props.get("amount", {}).get("number", 0) or 0
        cat_rel = props.get("category", {}).get("relation", [])
        cat_name = cat_names.get(cat_rel[0]["id"], "Senza categoria") if cat_rel else "Senza categoria"
        spending[cat_name] = spending.get(cat_name, 0) + abs(amount)
    return spending


async def _lookup_merchant_category(merchant: str) -> str | None:
    """Cerca merchant nel MerchantMap, ritorna category_id o None."""
    merchant_upper = merchant.upper().strip()
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(f"https://api.notion.com/v1/databases/{DB_MERCHANTMAP}/query", headers=HEADERS, json={"page_size": 100})
    for m in r.json().get("results", []):
        name_parts = m["properties"].get("merchant_raw", {}).get("title", [])
        name = name_parts[0]["plain_text"].upper() if name_parts else ""
        cat_rel = m["properties"].get("category", {}).get("relation", [])
        if cat_rel and (name == merchant_upper or name in merchant_upper or merchant_upper in name):
            return cat_rel[0]["id"]
    return None


async def add_transaction(merchant: str, amount: float, date_str: str = None) -> str:
    """Aggiunge transazione in Notion con categoria dal MerchantMap."""
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")
    cat_id = await _lookup_merchant_category(merchant)
    body = {
        "parent": {"database_id": DB_TRANSACTIONS},
        "properties": {
            "Name": {"title": [{"text": {"content": merchant}}]},
            "merchant_raw": {"rich_text": [{"text": {"content": merchant}}]},
            "amount": {"number": -abs(amount)},
            "date": {"date": {"start": date_str}},
        }
    }
    if cat_id:
        body["properties"]["category"] = {"relation": [{"id": cat_id}]}
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post("https://api.notion.com/v1/pages", headers=HEADERS, json=body)
    if r.status_code == 200:
        cat_names = await _get_all_category_names()
        cat_label = cat_names.get(cat_id, "Senza categoria") if cat_id else "Senza categoria"
        return f"✅ Aggiunta: *{merchant}* -€{abs(amount):.2f} → {cat_label}"
    return f"Errore aggiunta transazione: {r.status_code}"


def format_weekly_summary(spending: dict) -> str:
    if not spending:
        return "Nessuna spesa negli ultimi 7 giorni."
    lines = ["📊 *Spese ultimi 7 giorni*\n"]
    total = 0
    for cat, amt in sorted(spending.items(), key=lambda x: x[1], reverse=True):
        lines.append(f"• {cat}: €{amt:.2f}")
        total += amt
    lines.append(f"\n💰 *Totale: €{total:.2f}*")
    return "\n".join(lines)


def format_spending_summary(spending: dict) -> str:
    if not spending:
        return "Nessuna spesa registrata questo mese."
    lines = [f"📊 *Spese {datetime.now().strftime('%B %Y')}*\n"]
    total = 0
    for cat, amt in sorted(spending.items(), key=lambda x: x[1], reverse=True):
        lines.append(f"• {cat}: €{amt:.2f}")
        total += amt
    lines.append(f"\n💰 *Totale: €{total:.2f}*")
    return "\n".join(lines)


def format_alerts(alerts: list[dict]) -> str:
    if not alerts:
        return ""
    lines = []
    for a in alerts:
        emoji = "🚨" if a["level"] == "over" else "⚠️"
        lines.append(
            f"{emoji} *{a['category']}*: €{a['spent']:.0f}/€{a['budget']:.0f} ({a['pct']:.0f}%)"
        )
    return "\n".join(lines)
