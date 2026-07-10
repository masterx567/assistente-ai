import os
import re
import httpx
from datetime import datetime, timezone, timedelta, date

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
DB_TRANSACTIONS = os.getenv("NOTION_DB_TRANSACTIONS")
DB_CATEGORIES = os.getenv("NOTION_DB_CATEGORIES")
DB_MERCHANTMAP = "c82a1f2a-a1dc-421b-aeb8-e0fc4e413354"
DB_COMMITMENTS = "609fd00a-fe13-4900-bb2d-f460b134ea4e"

# Ancora fissa per il saldo Isybank: valore confermato manualmente dall'utente
# contro l'app della banca. Il saldo corrente si ricalcola sempre come
# ANCHOR_BALANCE + somma transazioni sincronizzate (source=api) dopo questa data —
# mai chiamando l'endpoint /balances (rate-limited su Isybank, 429 il 03/07/2026).
ISYBANK_ANCHOR_DATE = "2026-07-10"
ISYBANK_ANCHOR_BALANCE = 3996.39

_BNPL_KEYWORDS = ("KLARNA", "SCALAPAY", "PAGA IN 3 RATE", "PAYPAL *PAGA")
_RE_RATE_COUNT = re.compile(r'IN\s+(\d+)\s+RATE', re.I)

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = "llama-3.1-8b-instant"

EB_APP_ID = os.getenv("ENABLE_BANKING_APP_ID", "21fde8fa-b795-4e49-877d-438b309bc065")
EB_SESSION_ID = os.getenv("ENABLE_BANKING_SESSION_ID")
EB_SESSION_EXPIRY = os.getenv("ENABLE_BANKING_SESSION_EXPIRY", "2026-09-28")
EB_ACCOUNT_UID = os.getenv("ENABLE_BANKING_ACCOUNT_UID", "b070e7ad-96ff-416c-9d09-566fb5c23ca2")
_RAW_KEY = os.getenv("ENABLE_BANKING_PRIVATE_KEY", "")
EB_PRIVATE_KEY = _RAW_KEY.replace("\\n", "\n") if _RAW_KEY else None

EB_API = "https://api.enablebanking.com"
CATEGORIES = [
    "Supermercati", "Ristoranti & Bar", "Trasporti",
    "Abbonamenti & Streaming", "Salute", "Shopping",
    "Utenze & Casa", "Istruzione", "Tempo libero",
    "Stato", "Vacanze", "Altro",
]

NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}


# ── JWT ───────────────────────────────────────────────────────────────────────

def _make_jwt() -> str:
    import jwt as pyjwt
    iat = int(datetime.now().timestamp())
    return pyjwt.encode(
        {"iss": "enablebanking.com", "aud": "api.enablebanking.com", "iat": iat, "exp": iat + 3600},
        EB_PRIVATE_KEY.encode(),
        algorithm="RS256",
        headers={"kid": EB_APP_ID},
    )


def _eb_headers() -> dict:
    return {"Authorization": f"Bearer {_make_jwt()}"}


# ── Merchant extraction ───────────────────────────────────────────────────────

_RE_POS1 = re.compile(r'Pagamento su POS\s+(.+?)\s{3,}\d{2}/\d{2}', re.I)
_RE_POS2 = re.compile(r'PRESSO\s+(.+?)(?:\s{2,}|$)', re.I)
_RE_POS3 = re.compile(r'PAGAMENTO TRAMITE POS\s+(.+?)(?:\s+VIA[A-Z\s]|\s{3,}\d{2}/\d{2})', re.I)
_RE_NUM  = re.compile(r'\s*\d{4,}\s*$')


def _extract_merchant(remittance: str) -> tuple[str, str | None]:
    """
    Returns (merchant_raw, forced_category | None).
    forced_category è usato per casi speciali (stipendio, prelievo, ecc.)
    """
    t = remittance

    # Stipendio / Accredito
    if re.search(r'STIPENDIO|QUATTORDICESIMA|TREDICESIMA|RETRIBUZIONE', t, re.I):
        return "Stipendio", "Stato"
    if re.search(r'ACCREDITO BONIFICO', t, re.I):
        return "Accredito Bonifico", None
    if re.search(r'BANCOMAT PAY', t, re.I):
        m = re.search(r'BANCOMAT PAY Da (.+?) data:', t, re.I)
        return (m.group(1).strip() if m else "Bancomat Pay"), None
    if re.search(r'PRELIEVO SPORTELLO|PRELIEVO ATM', t, re.I):
        return "Prelievo ATM", "Altro"
    if re.search(r'ADDEBITO SALDO E/C CARTA', t, re.I):
        return "Carta di Credito", "Altro"
    if re.search(r'BONIFICO ISTANTANEO DA VOI', t, re.I):
        return "Bonifico Uscita", "Altro"

    # POS pattern 1: "Pagamento su POS {merchant}   DD/MM"
    m = _RE_POS1.search(t)
    if m:
        return _clean(m.group(1)), None

    # POS pattern 2: "...PRESSO {merchant}   "
    m = _RE_POS2.search(t)
    if m:
        return _clean(m.group(1)), None

    # POS pattern 3: "PAGAMENTO TRAMITE POS {merchant} VIA..."
    m = _RE_POS3.search(t)
    if m:
        return _clean(m.group(1)), None

    # Fallback: first 40 chars
    return t[:40].strip(), None


def _clean(name: str) -> str:
    name = name.strip()
    name = _RE_NUM.sub("", name).strip()
    return name


# ── Groq categorization ───────────────────────────────────────────────────────

async def _groq_categorize(merchant: str) -> str:
    cats = ", ".join(CATEGORIES)
    prompt = (
        f'Classifica il merchant "{merchant}" in una di queste categorie: {cats}. '
        f'Rispondi SOLO con il nome esatto della categoria.'
    )
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            json={
                "model": GROQ_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 20,
                "temperature": 0,
            },
        )
    raw = r.json().get("choices", [{}])[0].get("message", {}).get("content", "").strip()
    return raw if raw in CATEGORIES else "Altro"


# ── Notion helpers ────────────────────────────────────────────────────────────

async def _get_categories() -> dict[str, str]:
    """Returns {name: page_id}."""
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(
            f"https://api.notion.com/v1/databases/{DB_CATEGORIES}/query",
            headers=NOTION_HEADERS, json={"page_size": 100},
        )
    result = {}
    for page in r.json().get("results", []):
        parts = page["properties"].get("Name", {}).get("title", [])
        name = parts[0]["plain_text"] if parts else ""
        if name:
            result[name] = page["id"]
    return result


async def _merchant_lookup(merchant: str) -> str | None:
    """Returns category page_id if merchant found in MerchantMap, else None."""
    body = {
        "filter": {"property": "merchant_raw", "title": {"equals": merchant}},
        "page_size": 1,
    }
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.post(
            f"https://api.notion.com/v1/databases/{DB_MERCHANTMAP}/query",
            headers=NOTION_HEADERS, json=body,
        )
    results = r.json().get("results", [])
    if not results:
        return None
    cats = results[0]["properties"].get("category", {}).get("relation", [])
    return cats[0]["id"] if cats else None


async def _merchant_create(merchant: str, category_id: str) -> None:
    """Adds merchant → category mapping to MerchantMap."""
    async with httpx.AsyncClient(timeout=10) as c:
        await c.post(
            "https://api.notion.com/v1/pages",
            headers=NOTION_HEADERS,
            json={
                "parent": {"database_id": DB_MERCHANTMAP},
                "properties": {
                    "merchant_raw": {"title": [{"text": {"content": merchant}}]},
                    "category": {"relation": [{"id": category_id}]},
                },
            },
        )


async def _tx_exists(entry_ref: str) -> bool:
    """Returns True if entry_reference already in Transactions."""
    body = {
        "filter": {"property": "entry_reference", "rich_text": {"equals": entry_ref}},
        "page_size": 1,
    }
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.post(
            f"https://api.notion.com/v1/databases/{DB_TRANSACTIONS}/query",
            headers=NOTION_HEADERS, json=body,
        )
    return len(r.json().get("results", [])) > 0


async def _tx_save(tx: dict, merchant: str, category_id: str | None) -> None:
    amount_raw = float(tx["transaction_amount"]["amount"])
    amount = -amount_raw if tx.get("credit_debit_indicator") == "DBIT" else amount_raw
    tx_type = "income" if amount > 0 else "expense"
    rem = tx.get("remittance_information") or []
    desc = rem[0][:2000] if rem else ""

    props: dict = {
        "Name": {"title": [{"text": {"content": merchant[:100]}}]},
        "amount": {"number": amount},
        "date": {"date": {"start": tx["booking_date"]}},
        "type": {"select": {"name": tx_type}},
        "source": {"select": {"name": "api"}},
        "merchant_raw": {"rich_text": [{"text": {"content": merchant[:200]}}]},
        "entry_reference": {"rich_text": [{"text": {"content": tx.get("entry_reference", "")[:200]}}]},
        "merchant_normalized": {"rich_text": [{"text": {"content": merchant[:200]}}]},
        "notes": {"rich_text": [{"text": {"content": desc}}]},
        "reviewed": {"checkbox": False},
    }
    if category_id:
        props["category"] = {"relation": [{"id": category_id}]}

    async with httpx.AsyncClient(timeout=15) as c:
        await c.post(
            "https://api.notion.com/v1/pages",
            headers=NOTION_HEADERS,
            json={"parent": {"database_id": DB_TRANSACTIONS}, "properties": props},
        )


# ── BNPL (buy-now-pay-later) commitments ──────────────────────────────────────

async def _find_active_commitment(merchant: str, amount: float) -> dict | None:
    """Cerca piano attivo per merchant (case-insensitive — il testo remittance della banca
    non usa maiuscole/minuscole in modo coerente, es. "Klarna*Ticketone" vs "Klarna*ticketone"),
    con tolleranza ±10% sull'importo rata (evita duplicati per centesimi di differenza)."""
    body = {"filter": {"property": "amount_remaining", "number": {"greater_than": 0}}, "page_size": 20}
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.post(
            f"https://api.notion.com/v1/databases/{DB_COMMITMENTS}/query",
            headers=NOTION_HEADERS, json=body,
        )
    merchant_l = merchant.lower()
    for page in r.json().get("results", []):
        props = page["properties"]
        name_parts = props.get("Name", {}).get("title", [])
        name = (name_parts[0]["plain_text"] if name_parts else "").lower()
        if not name.startswith(merchant_l):
            continue
        remaining = props.get("amount_remaining", {}).get("number") or 0
        installment = props.get("monthly_installment", {}).get("number") or 0
        if remaining > 0 and installment > 0 and abs(installment - amount) / installment <= 0.10:
            return {"page_id": page["id"], "remaining": remaining}
    return None


async def _upsert_bnpl_commitment(merchant: str, amount: float, booking_date: str, remittance: str) -> None:
    existing = await _find_active_commitment(merchant, amount)
    plan_name = f"{merchant} (€{amount:.2f})"
    next_due = (date.fromisoformat(booking_date) + timedelta(days=30)).isoformat()

    if existing:
        new_remaining = max(0.0, existing["remaining"] - amount)
        props = {
            "amount_remaining": {"number": new_remaining},
            "monthly_installment": {"number": amount},
        }
        if new_remaining > 0:
            props["next_due"] = {"date": {"start": next_due}}
        async with httpx.AsyncClient(timeout=10) as c:
            await c.patch(f"https://api.notion.com/v1/pages/{existing['page_id']}", headers=NOTION_HEADERS, json={"properties": props})
        return

    m = _RE_RATE_COUNT.search(remittance)
    n_installments = int(m.group(1)) if m else 3
    amount_total = amount * n_installments
    amount_remaining = amount * (n_installments - 1)

    props = {
        "Name": {"title": [{"text": {"content": plan_name[:100]}}]},
        "amount_total": {"number": amount_total},
        "amount_remaining": {"number": amount_remaining},
        "monthly_installment": {"number": amount},
    }
    if amount_remaining > 0:
        props["next_due"] = {"date": {"start": next_due}}
    async with httpx.AsyncClient(timeout=10) as c:
        await c.post(
            "https://api.notion.com/v1/pages",
            headers=NOTION_HEADERS,
            json={"parent": {"database_id": DB_COMMITMENTS}, "properties": props},
        )


# ── Enable Banking fetch ──────────────────────────────────────────────────────

async def _sum_synced_since(since_date: str) -> float:
    """Somma le transazioni sincronizzate (source=api) con date > since_date.
    Usata per aggiornare il saldo senza chiamare l'endpoint /balances (rate-limited)."""
    body = {
        "filter": {"and": [
            {"property": "source", "select": {"equals": "api"}},
            {"property": "date", "date": {"after": since_date}},
        ]},
        "page_size": 100,
    }
    total = 0.0
    async with httpx.AsyncClient(timeout=15) as c:
        while True:
            r = await c.post(f"https://api.notion.com/v1/databases/{DB_TRANSACTIONS}/query", headers=NOTION_HEADERS, json=body)
            data = r.json()
            for page in data.get("results", []):
                total += page["properties"].get("amount", {}).get("number") or 0
            if not data.get("has_more"):
                break
            body["start_cursor"] = data["next_cursor"]
    return total


class EBAuthError(Exception):
    """Sessione/consenso Enable Banking non più valido (serve ri-autorizzare)."""


async def _fetch_transactions(days_back: int = 3) -> list[dict]:
    if not EB_SESSION_ID or not EB_PRIVATE_KEY:
        return []
    date_from = (datetime.now(timezone.utc) - timedelta(days=days_back)).date().isoformat()
    params = {"date_from": date_from}
    all_txs = []
    async with httpx.AsyncClient(timeout=30) as c:
        while True:
            r = await c.get(
                f"{EB_API}/accounts/{EB_ACCOUNT_UID}/transactions",
                params=params,
                headers=_eb_headers(),
            )
            if r.status_code == 401:
                err = r.json().get("error", "EXPIRED_SESSION") if r.headers.get("content-type", "").startswith("application/json") else "EXPIRED_SESSION"
                raise EBAuthError(err)
            if r.status_code != 200:
                break
            data = r.json()
            all_txs.extend(data.get("transactions", []))
            ck = data.get("continuation_key")
            if not ck:
                break
            params["continuation_key"] = ck
    return all_txs


# ── Main sync ─────────────────────────────────────────────────────────────────

async def sync_transactions(days_back: int = 3) -> dict:
    """Full pipeline: fetch → dedup → categorize → save transazioni, poi ricalcola
    il saldo Isybank sommando i movimenti sincronizzati dall'ancora fissa (niente
    chiamate a /balances, che va in rate limit su Isybank)."""
    from agents.budget import save_account_balance

    try:
        txs = await _fetch_transactions(days_back)
    except EBAuthError as e:
        return {"fetched": 0, "saved": 0, "skipped": 0, "auth_error": str(e)}

    if not txs:
        result = {"fetched": 0, "saved": 0, "skipped": 0, "error": "No transactions or missing config"}
    else:
        cats = await _get_categories()  # {name: page_id}
        saved = skipped = 0

        for tx in txs:
            entry_ref = tx.get("entry_reference", "")
            if entry_ref and await _tx_exists(entry_ref):
                skipped += 1
                continue

            rem = tx.get("remittance_information") or [""]
            merchant, forced_cat = _extract_merchant(rem[0])

            # BNPL: aggiorna piano ammortamento invece di categorizzare normalmente
            if any(kw in merchant.upper() or kw in rem[0].upper() for kw in _BNPL_KEYWORDS):
                amount = abs(float(tx["transaction_amount"]["amount"]))
                await _upsert_bnpl_commitment(merchant, amount, tx["booking_date"], rem[0])
                forced_cat = forced_cat or "Shopping"

            # Resolve category
            category_id: str | None = None
            if forced_cat:
                category_id = cats.get(forced_cat)
            else:
                category_id = await _merchant_lookup(merchant)
                if not category_id:
                    cat_name = await _groq_categorize(merchant)
                    category_id = cats.get(cat_name) or cats.get("Altro")
                    if category_id:
                        await _merchant_create(merchant, category_id)

            await _tx_save(tx, merchant, category_id)
            saved += 1

        result = {"fetched": len(txs), "saved": saved, "skipped": skipped}

    delta = await _sum_synced_since(ISYBANK_ANCHOR_DATE)
    await save_account_balance("Isybank", ISYBANK_ANCHOR_BALANCE + delta, "bank")
    result["balance_synced"] = True
    return result


# ── OAuth reminder ────────────────────────────────────────────────────────────

def session_expiry_days() -> int:
    """Days until Enable Banking session expires. Negative = already expired."""
    try:
        exp = date.fromisoformat(EB_SESSION_EXPIRY)
        return (exp - date.today()).days
    except Exception:
        return 999
