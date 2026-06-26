import httpx
import asyncio
import calendar as _calendar
from datetime import datetime, timedelta, date
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


async def get_all_categories() -> list[dict]:
    """Ritorna lista [{id, name}] di tutte le categorie."""
    names = await _get_all_category_names()
    return [{"id": k, "name": v} for k, v in sorted(names.items(), key=lambda x: x[1])]


async def _get_spending(year: int, month: int) -> dict:
    """Ritorna spese per categoria per un dato mese."""
    start = f"{year}-{month:02d}-01"
    end = f"{year}-{month:02d}-{_last_day(year, month):02d}"
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
    cursor = None
    async with httpx.AsyncClient(timeout=30) as client:
        while True:
            if cursor:
                body["start_cursor"] = cursor
            r = await client.post(f"https://api.notion.com/v1/databases/{DB_TRANSACTIONS}/query", headers=HEADERS, json=body)
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


async def get_monthly_comparison() -> str:
    """Confronta spese mese corrente vs mese scorso."""
    now = datetime.now()
    prev_month = now.month - 1 if now.month > 1 else 12
    prev_year = now.year if now.month > 1 else now.year - 1
    month_names = ["", "Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno",
                   "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre"]

    curr, prev = await asyncio.gather(_get_spending(now.year, now.month), _get_spending(prev_year, prev_month))
    all_cats = sorted(set(list(curr.keys()) + list(prev.keys())))

    curr_total = sum(curr.values())
    prev_total = sum(prev.values())
    diff_total = curr_total - prev_total
    diff_emoji = "🔴" if diff_total > 0 else "🟢"

    lines = [f"📊 *{month_names[now.month]} vs {month_names[prev_month]}*\n"]
    for cat in all_cats:
        c = curr.get(cat, 0)
        p = prev.get(cat, 0)
        if c == 0 and p == 0:
            continue
        diff = c - p
        arrow = "↑" if diff > 0 else ("↓" if diff < 0 else "→")
        lines.append(f"• *{cat}*: €{c:.0f} {arrow} (€{p:.0f})")
    lines.append(f"\n{diff_emoji} *Totale*: €{curr_total:.0f} vs €{prev_total:.0f} ({'+' if diff_total >= 0 else ''}{diff_total:.0f})")
    return "\n".join(lines)


async def get_monthly_spending() -> dict:
    """Ritorna spese mese corrente per categoria."""
    now = datetime.now()
    return await _get_spending(now.year, now.month)


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
    async with httpx.AsyncClient(timeout=15) as client:
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
    async with httpx.AsyncClient(timeout=15) as client:
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


async def lookup_merchant(merchant: str) -> dict:
    """Cerca merchant nel MerchantMap, ritorna {cat_id, cat_name}."""
    cat_id = await _lookup_merchant_category(merchant)
    if cat_id:
        cat_names = await _get_all_category_names()
        return {"cat_id": cat_id, "cat_name": cat_names.get(cat_id, "Senza categoria")}
    return {"cat_id": None, "cat_name": "Senza categoria"}


async def save_merchant_map(merchant: str, cat_id: str) -> bool:
    """Aggiunge voce nel MerchantMap."""
    body = {
        "parent": {"database_id": DB_MERCHANTMAP},
        "properties": {
            "merchant_raw": {"title": [{"text": {"content": merchant.upper().strip()}}]},
            "category": {"relation": [{"id": cat_id}]},
        }
    }
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post("https://api.notion.com/v1/pages", headers=HEADERS, json=body)
    return r.status_code == 200


async def add_transaction(merchant: str, amount: float, date_str: str = None, cat_id: str = None) -> str:
    """Aggiunge transazione in Notion. cat_id opzionale: se None fa lookup MerchantMap."""
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")
    if cat_id is None:
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


async def delete_transaction(merchant: str, amount: float = None, date_str: str = None) -> str:
    """Cerca e cancella una transazione in Notion per merchant (+ opzionale amount/date)."""
    filters = [{"property": "merchant_raw", "rich_text": {"contains": merchant}}]
    if amount:
        filters.append({"property": "amount", "number": {"equals": -abs(amount)}})
    if date_str:
        filters.append({"property": "date", "date": {"equals": date_str}})

    body = {
        "filter": {"and": filters} if len(filters) > 1 else filters[0],
        "sorts": [{"property": "date", "direction": "descending"}],
        "page_size": 5,
    }
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(f"https://api.notion.com/v1/databases/{DB_TRANSACTIONS}/query", headers=HEADERS, json=body)
    results = r.json().get("results", [])
    if not results:
        return f"Nessuna transazione trovata con '{merchant}'."

    page = results[0]
    page_id = page["id"]
    props = page["properties"]
    amt = props.get("amount", {}).get("number", 0)
    mr = props.get("merchant_raw", {}).get("rich_text", [])
    name = mr[0]["plain_text"] if mr else merchant

    async with httpx.AsyncClient(timeout=15) as client:
        r2 = await client.patch(f"https://api.notion.com/v1/pages/{page_id}", headers=HEADERS, json={"archived": True})
    if r2.status_code == 200:
        return f"🗑️ Eliminata: *{name}* €{abs(amt):.2f}"
    return f"Errore eliminazione: {r2.status_code}"


async def get_recent_transactions(limit: int = 10) -> list[dict]:
    """Ultime N transazioni (uscite) ordinate per data."""
    body = {"filter": {"property": "amount", "number": {"less_than": 0}},
            "sorts": [{"property": "date", "direction": "descending"}],
            "page_size": limit}
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(f"https://api.notion.com/v1/databases/{DB_TRANSACTIONS}/query", headers=HEADERS, json=body)
    results = []
    for t in r.json().get("results", [])[:limit]:
        props = t["properties"]
        amount = props.get("amount", {}).get("number", 0) or 0
        date_str = (props.get("date", {}).get("date") or {}).get("start", "")[:10]
        mr = props.get("merchant_raw", {}).get("rich_text", [])
        mn = props.get("merchant_normalized", {}).get("rich_text", [])
        title_parts = props.get("Name", {}).get("title", [])
        name = (mr[0]["plain_text"] if mr else
                mn[0]["plain_text"] if mn else
                title_parts[0]["plain_text"] if title_parts else "?")
        results.append({"name": name, "amount": abs(amount), "date": date_str})
    return results


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


async def get_remaining_budget(cat_query: str) -> str:
    """Budget rimanente per una categoria (ricerca fuzzy sul nome)."""
    budgets, spending = await asyncio.gather(get_category_budgets(), get_monthly_spending())
    cat_query_l = cat_query.lower()
    matched = next(
        (name for name in budgets if cat_query_l in name.lower() or name.lower() in cat_query_l),
        None
    )
    if not matched:
        cats = ", ".join(sorted(budgets.keys()))
        return f"Categoria '{cat_query}' non trovata. Disponibili: {cats}"
    budget = budgets[matched]
    if budget <= 0:
        return f"Nessun budget impostato per *{matched}*."
    spent = spending.get(matched, 0)
    remaining = budget - spent
    pct = spent / budget * 100
    if remaining > 0:
        emoji = "🟢" if pct < 80 else "⚠️"
        return f"{emoji} *{matched}*: €{spent:.0f}/€{budget:.0f} ({pct:.0f}%)\nTi rimangono *€{remaining:.0f}*."
    return f"🚨 *{matched}*: sforato di €{abs(remaining):.0f}! (€{spent:.0f}/€{budget:.0f}, {pct:.0f}%)"


_MONTHS_IT = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4,
    "maggio": 5, "giugno": 6, "luglio": 7, "agosto": 8,
    "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
}


async def get_transactions_by_period(period: str, limit: int = 20) -> list[dict]:
    """Transazioni filtrate per periodo (settimana / mese corrente / nome mese)."""
    today = date.today()
    now = datetime.now()
    period_l = period.lower().strip()

    if "settimana" in period_l:
        start = today - timedelta(days=7)
        end = today
    else:
        matched_month = next((num for name, num in _MONTHS_IT.items() if name in period_l), None)
        if matched_month:
            year = now.year if matched_month <= now.month else now.year - 1
            last_day = _calendar.monthrange(year, matched_month)[1]
            start = date(year, matched_month, 1)
            end = date(year, matched_month, last_day)
        else:
            start = date(now.year, now.month, 1)
            end = today

    body = {
        "filter": {"and": [
            {"property": "date", "date": {"on_or_after": start.isoformat()}},
            {"property": "date", "date": {"on_or_before": end.isoformat()}},
            {"property": "amount", "number": {"less_than": 0}},
        ]},
        "sorts": [{"property": "date", "direction": "descending"}],
        "page_size": limit,
    }
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(
            f"https://api.notion.com/v1/databases/{DB_TRANSACTIONS}/query",
            headers=HEADERS, json=body
        )
    results = []
    for t in r.json().get("results", [])[:limit]:
        props = t["properties"]
        amount = props.get("amount", {}).get("number", 0) or 0
        date_str = (props.get("date", {}).get("date") or {}).get("start", "")[:10]
        mr = props.get("merchant_raw", {}).get("rich_text", [])
        title_parts = props.get("Name", {}).get("title", [])
        name = mr[0]["plain_text"] if mr else (title_parts[0]["plain_text"] if title_parts else "?")
        results.append({"name": name, "amount": abs(amount), "date": date_str})
    return results, start, end


async def add_income(source: str, amount: float, date_str: str = None) -> str:
    """Aggiunge entrata positiva in Notion."""
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")
    body = {
        "parent": {"database_id": DB_TRANSACTIONS},
        "properties": {
            "Name": {"title": [{"text": {"content": source}}]},
            "merchant_raw": {"rich_text": [{"text": {"content": source}}]},
            "amount": {"number": abs(amount)},
            "date": {"date": {"start": date_str}},
        }
    }
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post("https://api.notion.com/v1/pages", headers=HEADERS, json=body)
    if r.status_code == 200:
        return f"💰 Entrata aggiunta: *{source}* +€{abs(amount):.2f}"
    return f"Errore aggiunta entrata: {r.status_code}"


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
