import httpx
import asyncio
import re
import calendar as _calendar
from datetime import datetime, timedelta, date
import os

_MESI_IT = ["", "Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno",
            "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre"]


def mese_anno_it(d) -> str:
    return f"{_MESI_IT[d.month]} {d.year}"


NOTION_TOKEN = os.getenv("NOTION_TOKEN")
DB_TRANSACTIONS = os.getenv("NOTION_DB_TRANSACTIONS")
DB_CATEGORIES = os.getenv("NOTION_DB_CATEGORIES")

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
    lines = [f"📊 *Spese {mese_anno_it(datetime.now())}*\n"]
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


async def _get_transactions_since(days_back: int) -> list[dict]:
    """Tutte le uscite (expense) negli ultimi N giorni, con merchant/amount/date/category."""
    start = (date.today() - timedelta(days=days_back)).isoformat()
    cat_names = await _get_all_category_names()
    body = {
        "filter": {"and": [
            {"property": "date", "date": {"on_or_after": start}},
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

    results = []
    for t in transactions:
        props = t["properties"]
        amount = abs(props.get("amount", {}).get("number", 0) or 0)
        date_str = (props.get("date", {}).get("date") or {}).get("start", "")[:10]
        mr = props.get("merchant_raw", {}).get("rich_text", [])
        merchant = mr[0]["plain_text"] if mr else "?"
        cat_rel = props.get("category", {}).get("relation", [])
        cat_name = cat_names.get(cat_rel[0]["id"], "Senza categoria") if cat_rel else "Senza categoria"
        if date_str:
            results.append({"merchant": merchant, "amount": amount, "date": date_str, "category": cat_name})
    return results


_BNPL_KEYWORDS = ("KLARNA", "SCALAPAY", "PAGA IN 3 RATE", "PAYPAL *PAGA")


async def detect_subscriptions(days_back: int = 90) -> list[dict]:
    """Trova merchant con addebito ciclico ~mensile (intervallo 25-35gg stabile, importo stabile ±8%)."""
    txs = await _get_transactions_since(days_back)
    by_merchant: dict[str, list[dict]] = {}
    for t in txs:
        by_merchant.setdefault(t["merchant"], []).append(t)

    subs = []
    for merchant, entries in by_merchant.items():
        if any(kw in merchant.upper() for kw in _BNPL_KEYWORDS):
            continue
        if len(entries) < 2:
            continue
        entries = sorted(entries, key=lambda e: e["date"])
        dates = [date.fromisoformat(e["date"]) for e in entries]
        deltas = [(dates[i] - dates[i - 1]).days for i in range(1, len(dates))]
        if not all(25 <= d <= 35 for d in deltas):
            continue

        amounts = [e["amount"] for e in entries]
        avg = sum(amounts) / len(amounts)
        if avg == 0 or any(abs(a - avg) / avg > 0.08 for a in amounts):
            continue

        avg_interval = round(sum(deltas) / len(deltas))
        last_date = dates[-1]
        next_expected = last_date + timedelta(days=avg_interval)
        subs.append({
            "merchant": merchant, "amount": avg,
            "last_charge": last_date.isoformat(),
            "next_expected": next_expected.isoformat(),
        })
    return subs


async def check_subscription_reminders() -> list[str]:
    """Ritorna messaggi reminder per abbonamenti con addebito atteso nei prossimi 2 giorni."""
    subs = await detect_subscriptions()
    today = date.today()
    messages = []
    for s in subs:
        next_expected = date.fromisoformat(s["next_expected"])
        if 0 <= (next_expected - today).days <= 2:
            messages.append(f"🔔 *{s['merchant']}* ~€{s['amount']:.2f} previsto circa il {next_expected.strftime('%d/%m')}.")
    return messages


async def get_food_digest(days_back: int = 7) -> dict[str, dict]:
    """Spese bar/ristoranti/fast-food raggruppate per merchant, ultimi N giorni."""
    txs = await _get_transactions_since(days_back)
    food = [t for t in txs if t["category"] in ("Ristoranti & Bar",)]
    digest: dict[str, dict] = {}
    for t in food:
        d = digest.setdefault(t["merchant"], {"count": 0, "total": 0.0})
        d["count"] += 1
        d["total"] += t["amount"]
    return digest


def format_food_digest(digest: dict[str, dict]) -> str:
    if not digest:
        return ""
    lines = ["\n🍔 *Bar & fast-food ultimi 7 giorni*"]
    total = 0.0
    for merchant, d in sorted(digest.items(), key=lambda x: x[1]["total"], reverse=True):
        lines.append(f"• {merchant} x{d['count']}: €{d['total']:.2f}")
        total += d["total"]
    lines.append(f"_Totale piccole spese: €{total:.2f}_")
    return "\n".join(lines)


DB_COMMITMENTS = "609fd00a-fe13-4900-bb2d-f460b134ea4e"
DB_ACCOUNTS = "13ed0283-e81f-4c95-8c04-57bdc4d15ff5"


async def save_account_balance(name: str, balance: float, acc_type: str) -> None:
    """Crea o aggiorna un conto in Accounts (cerca by Name esatto)."""
    body = {"filter": {"property": "Name", "title": {"equals": name}}, "page_size": 1}
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(f"https://api.notion.com/v1/databases/{DB_ACCOUNTS}/query", headers=HEADERS, json=body)
    results = r.json().get("results", [])
    today_str = date.today().isoformat()
    props = {
        "balance": {"number": balance},
        "type": {"select": {"name": acc_type}},
        "last_updated": {"date": {"start": today_str}},
    }
    async with httpx.AsyncClient(timeout=10) as client:
        if results:
            await client.patch(f"https://api.notion.com/v1/pages/{results[0]['id']}", headers=HEADERS, json={"properties": props})
        else:
            props["Name"] = {"title": [{"text": {"content": name}}]}
            await client.post("https://api.notion.com/v1/pages", headers=HEADERS, json={"parent": {"database_id": DB_ACCOUNTS}, "properties": props})


async def add_loan(person: str, amount: float) -> str:
    """Registra un prestito dato a una persona (conta positivo nel patrimonio)."""
    name = f"Prestito a {person.strip().title()}"
    await save_account_balance(name, amount, "credito")
    return f"✅ Registrato: *{name}* — €{amount:.2f}"


async def get_loans() -> str:
    """Lista prestiti dati (Accounts type=credito)."""
    body = {"filter": {"property": "type", "select": {"equals": "credito"}}, "page_size": 50}
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(f"https://api.notion.com/v1/databases/{DB_ACCOUNTS}/query", headers=HEADERS, json=body)
    results = r.json().get("results", [])
    if not results:
        return "Nessun prestito registrato."
    lines = ["🤝 *Prestiti dati*\n"]
    total = 0.0
    for a in results:
        props = a["properties"]
        name_parts = props.get("Name", {}).get("title", [])
        name = name_parts[0]["plain_text"] if name_parts else "?"
        balance = props.get("balance", {}).get("number") or 0
        lines.append(f"• {name}: €{balance:.2f}")
        total += balance
    lines.append(f"\n💰 *Totale: €{total:.2f}*")
    return "\n".join(lines)


DB_NETWORTH_HISTORY = "56661457-1b84-476d-98d6-c25d8a260732"


async def _compute_net_worth() -> tuple[float, list[str]]:
    async with httpx.AsyncClient(timeout=15) as client:
        r_acc = await client.post(f"https://api.notion.com/v1/databases/{DB_ACCOUNTS}/query", headers=HEADERS, json={"page_size": 50})
        r_com = await client.post(
            f"https://api.notion.com/v1/databases/{DB_COMMITMENTS}/query", headers=HEADERS,
            json={"filter": {"property": "amount_remaining", "number": {"greater_than": 0}}, "page_size": 50},
        )

    accounts = r_acc.json().get("results", [])
    lines = []
    total = 0.0
    for a in accounts:
        props = a["properties"]
        name_parts = props.get("Name", {}).get("title", [])
        name = name_parts[0]["plain_text"] if name_parts else "?"
        balance = props.get("balance", {}).get("number") or 0
        acc_type = (props.get("type", {}).get("select") or {}).get("name", "")
        sign = -1 if acc_type == "debt" else 1
        total += sign * balance
        lines.append(f"• {name}: €{balance:.2f} ({acc_type})")

    bnpl_remaining = sum((c["properties"].get("amount_remaining", {}).get("number") or 0) for c in r_com.json().get("results", []))
    if bnpl_remaining:
        lines.append(f"• Rate BNPL da pagare: -€{bnpl_remaining:.2f}")
        total -= bnpl_remaining

    return total, lines


async def get_net_worth() -> str:
    """Patrimonio netto: somma Accounts (bank/investment/cash/credito) - debt - rate BNPL rimanenti. Salva snapshot storico."""
    total, lines = await _compute_net_worth()
    if not lines:
        return "Nessun conto registrato in Accounts."
    await record_net_worth_snapshot(total)
    return "🏦 *Patrimonio*\n\n" + "\n".join(lines) + f"\n\n💰 *Patrimonio netto: €{total:.2f}*"


async def record_net_worth_snapshot(total: float) -> None:
    """Salva uno snapshot mensile del patrimonio (per trend storico)."""
    today = date.today()
    name = mese_anno_it(today)
    body = {"filter": {"property": "Name", "title": {"equals": name}}, "page_size": 1}
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(f"https://api.notion.com/v1/databases/{DB_NETWORTH_HISTORY}/query", headers=HEADERS, json=body)
    results = r.json().get("results", [])
    props = {"total": {"number": total}, "date": {"date": {"start": today.isoformat()}}}
    async with httpx.AsyncClient(timeout=10) as client:
        if results:
            await client.patch(f"https://api.notion.com/v1/pages/{results[0]['id']}", headers=HEADERS, json={"properties": props})
        else:
            props["Name"] = {"title": [{"text": {"content": name}}]}
            await client.post("https://api.notion.com/v1/pages", headers=HEADERS, json={"parent": {"database_id": DB_NETWORTH_HISTORY}, "properties": props})


async def get_net_worth_trend() -> str:
    """Storico patrimonio nel tempo con variazione rispetto al mese precedente."""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(
            f"https://api.notion.com/v1/databases/{DB_NETWORTH_HISTORY}/query", headers=HEADERS,
            json={"sorts": [{"property": "date", "direction": "ascending"}], "page_size": 50},
        )
    snapshots = r.json().get("results", [])
    if not snapshots:
        return "Nessuno storico patrimonio ancora registrato."
    lines = ["📈 *Andamento patrimonio*\n"]
    prev = None
    for s in snapshots:
        props = s["properties"]
        name_parts = props.get("Name", {}).get("title", [])
        name = name_parts[0]["plain_text"] if name_parts else "?"
        total = props.get("total", {}).get("number") or 0
        delta = f" ({'+' if total - prev >= 0 else ''}{total - prev:.2f})" if prev is not None else ""
        lines.append(f"• {name}: €{total:.2f}{delta}")
        prev = total
    return "\n".join(lines)


async def get_month_projection() -> str:
    """Proiezione lineare spesa fine mese basata sul ritmo attuale, totale e per categoria."""
    now = datetime.now()
    spending, budgets = await asyncio.gather(get_monthly_spending(), get_category_budgets())
    spent_so_far = sum(spending.values())
    days_elapsed = now.day
    days_total = _last_day(now.year, now.month)
    if days_elapsed == 0 or spent_so_far == 0:
        return "Non ci sono ancora abbastanza spese questo mese per una proiezione."
    daily_rate = spent_so_far / days_elapsed
    projected = daily_rate * days_total
    remaining_days = days_total - days_elapsed

    over_budget = []
    for cat, spent in spending.items():
        budget = budgets.get(cat, 0)
        if budget <= 0:
            continue
        cat_projected = spent / days_elapsed * days_total
        if cat_projected > budget:
            over_budget.append((cat, cat_projected, budget))
    over_budget.sort(key=lambda x: x[1] / x[2], reverse=True)

    lines = [
        f"📈 *Proiezione fine mese*\n",
        f"Speso finora: €{spent_so_far:.2f} ({days_elapsed}/{days_total} giorni)",
        f"Ritmo medio: €{daily_rate:.2f}/giorno",
        f"Proiezione fine mese: *€{projected:.2f}*",
        f"({remaining_days} giorni rimasti, stimati altri €{daily_rate * remaining_days:.2f})",
    ]
    if over_budget:
        lines.append("\n⚠️ *Categorie a rischio sforamento:*")
        for cat, cat_projected, budget in over_budget:
            lines.append(f"• {cat}: proiezione €{cat_projected:.0f} vs budget €{budget:.0f}")
    return "\n".join(lines)


async def check_loan_reminders() -> list[str]:
    """Ritorna reminder per prestiti dati non aggiornati da >30 giorni."""
    body = {"filter": {"property": "type", "select": {"equals": "credito"}}, "page_size": 50}
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(f"https://api.notion.com/v1/databases/{DB_ACCOUNTS}/query", headers=HEADERS, json=body)
    today = date.today()
    messages = []
    for a in r.json().get("results", []):
        props = a["properties"]
        name_parts = props.get("Name", {}).get("title", [])
        name = name_parts[0]["plain_text"] if name_parts else "?"
        balance = props.get("balance", {}).get("number") or 0
        last_updated_iso = (props.get("last_updated", {}).get("date") or {}).get("start", "")[:10]
        if not last_updated_iso or balance <= 0:
            continue
        last_updated = date.fromisoformat(last_updated_iso)
        days_since = (today - last_updated).days
        if days_since >= 30 and days_since % 30 == 0:
            messages.append(f"🤝 *{name}* (€{balance:.2f}) — è tornato indietro? Rispondi \"restituito {name.replace('Prestito a ', '')}\" se sì.")
    return messages


async def mark_loan_returned(person: str) -> str:
    """Segna un prestito come restituito (archivia l'account)."""
    name = f"Prestito a {person.strip().title()}"
    body = {"filter": {"property": "Name", "title": {"equals": name}}, "page_size": 1}
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(f"https://api.notion.com/v1/databases/{DB_ACCOUNTS}/query", headers=HEADERS, json=body)
    results = r.json().get("results", [])
    if not results:
        return f"Nessun prestito trovato per '{person}'."
    async with httpx.AsyncClient(timeout=10) as client:
        await client.patch(f"https://api.notion.com/v1/pages/{results[0]['id']}", headers=HEADERS, json={"archived": True})
    return f"✅ *{name}* segnato come restituito."


async def get_spending_anomalies(months_back: int = 3) -> list[str]:
    """Categorie con spesa di questo mese anomala rispetto alla media degli ultimi N mesi."""
    now = datetime.now()
    history = []
    for i in range(1, months_back + 1):
        m = now.month - i
        y = now.year
        while m <= 0:
            m += 12
            y -= 1
        history.append(await _get_spending(y, m))

    if not history:
        return []

    avg_by_cat: dict[str, float] = {}
    for cat_spending in history:
        for cat, amt in cat_spending.items():
            avg_by_cat.setdefault(cat, []).append(amt)
    avg_by_cat = {cat: sum(vals) / len(vals) for cat, vals in avg_by_cat.items()}

    current = await get_monthly_spending()
    anomalies = []
    for cat, spent in current.items():
        avg = avg_by_cat.get(cat, 0)
        if avg > 10 and spent > avg * 1.5:
            pct = (spent / avg - 1) * 100
            anomalies.append(f"⚠️ *{cat}*: €{spent:.2f} vs media €{avg:.2f} (+{pct:.0f}%)")
    return anomalies


def _strip_md(text: str) -> str:
    """Rimuove caratteri markdown (*, _) da testo dinamico (nomi merchant) prima di
    wrapparlo in *grassetto* — un '*' letterale nel nome (es. 'KLARNA*TICKETONE')
    spacca il parsing Markdown di Telegram e manda l'intero messaggio in plain text."""
    return text.replace("*", "").replace("_", "")


async def get_amortization_table() -> str:
    """Tabella piani BNPL attivi: totale, rimanente, rate rimaste, prossima scadenza."""
    body = {
        "filter": {"property": "amount_remaining", "number": {"greater_than": 0}},
        "page_size": 50,
    }
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(f"https://api.notion.com/v1/databases/{DB_COMMITMENTS}/query", headers=HEADERS, json=body)
    plans = r.json().get("results", [])
    if not plans:
        return "✅ Nessun piano di ammortamento attivo."

    lines = ["💳 *Piani di ammortamento attivi*\n"]
    tot_installment = 0.0
    tot_remaining = 0.0
    for p in plans:
        props = p["properties"]
        name_parts = props.get("Name", {}).get("title", [])
        name = name_parts[0]["plain_text"] if name_parts else "?"
        name = re.sub(r"\s*\(€[\d.,]+\)\s*$", "", name).strip()
        name = _strip_md(name)
        total = props.get("amount_total", {}).get("number") or 0
        remaining = props.get("amount_remaining", {}).get("number") or 0
        installment = props.get("monthly_installment", {}).get("number") or 0
        due_iso = (props.get("next_due", {}).get("date") or {}).get("start", "")[:10]
        due = "n/d"
        if due_iso:
            try:
                due = date.fromisoformat(due_iso).strftime("%d/%m/%Y")
            except ValueError:
                due = due_iso
        rate_rimaste = round(remaining / installment) if installment else 0
        rate_totali = round(total / installment) if installment else 0
        rata_corrente = rate_totali - rate_rimaste + 1
        lines.append(
            f"• *{name}* (€{installment:.2f}/rata)\n"
            f"   rata {rata_corrente}/{rate_totali} — €{remaining:.2f} rimanenti su €{total:.2f}\n"
            f"   prossima: {due}"
        )
        tot_installment += installment
        tot_remaining += remaining

    lines.append(f"\n📊 *Totale rate mensili: €{tot_installment:.2f}*\n📊 *Totale ancora da pagare: €{tot_remaining:.2f}*")
    return "\n\n".join(lines)


async def check_commitment_reminders() -> list[str]:
    """Ritorna messaggi reminder per rate BNPL in scadenza nei prossimi 2 giorni."""
    today = date.today()
    limit = (today + timedelta(days=2)).isoformat()
    body = {
        "filter": {"and": [
            {"property": "next_due", "date": {"on_or_before": limit}},
            {"property": "amount_remaining", "number": {"greater_than": 0}},
        ]},
        "page_size": 20,
    }
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(f"https://api.notion.com/v1/databases/{DB_COMMITMENTS}/query", headers=HEADERS, json=body)
    messages = []
    for c in r.json().get("results", []):
        props = c["properties"]
        name_parts = props.get("Name", {}).get("title", [])
        name = name_parts[0]["plain_text"] if name_parts else "?"
        name = _strip_md(name)
        installment = props.get("monthly_installment", {}).get("number") or 0
        remaining = props.get("amount_remaining", {}).get("number") or 0
        due_iso = (props.get("next_due", {}).get("date") or {}).get("start", "")[:10]
        due = "n/d"
        if due_iso:
            try:
                due = date.fromisoformat(due_iso).strftime("%d/%m/%Y")
            except ValueError:
                due = due_iso
        messages.append(f"💳 *{name}*: rata ~€{installment:.2f} prevista il {due} (rimangono €{remaining:.2f}).")
    return messages


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
