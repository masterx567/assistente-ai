import httpx
import os
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
DB_IRRIGAZIONE = "41a6389f8060493f80a2976518fd528c"
ROME = ZoneInfo("Europe/Rome")
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}

# Cormano (via Lario)
LAT, LON = 45.53, 9.15

# Config statica lato codice (nome deve combaciare col titolo su Notion).
# Stato mutevole (intervallo/ultimo annaffiato/streak) vive su Notion, non qui.
CONTAINERS = {
    "f": {"nome": "Fioriera", "ml": "300-400ml"},
    "v": {"nome": "Vaso alto", "ml": "1-1.5L"},
}


def _parse_page(p: dict) -> dict:
    props = p["properties"]
    title_parts = props.get("Contenitore", {}).get("title", [])
    nome = title_parts[0]["plain_text"] if title_parts else ""
    piante_parts = props.get("Piante", {}).get("rich_text", [])
    piante = piante_parts[0]["plain_text"] if piante_parts else ""
    intervallo = props.get("Intervallo", {}).get("number") or 0
    streak = props.get("Streak", {}).get("number") or 0
    ultimo_raw = props.get("UltimoAnnaffiato", {}).get("date")
    ultimo = date.fromisoformat(ultimo_raw["start"][:10]) if ultimo_raw else None
    return {"id": p["id"], "nome": nome, "piante": piante, "intervallo": intervallo,
            "streak": streak, "ultimo": ultimo}


async def get_all_containers() -> list[dict]:
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(f"https://api.notion.com/v1/databases/{DB_IRRIGAZIONE}/query",
            headers=HEADERS, json={"page_size": 20})
    return [_parse_page(p) for p in r.json().get("results", [])]


async def _get_container(nome: str) -> dict | None:
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(f"https://api.notion.com/v1/databases/{DB_IRRIGAZIONE}/query",
            headers=HEADERS, json={
                "filter": {"property": "Contenitore", "title": {"equals": nome}},
                "page_size": 1,
            })
    results = r.json().get("results", [])
    return _parse_page(results[0]) if results else None


def giorni_ritardo(container: dict, oggi: date) -> int | None:
    """None = mai annaffiato (non ancora avviato). Positivo = giorni di ritardo sull'intervallo."""
    if container["ultimo"] is None:
        return None
    giorni_passati = (oggi - container["ultimo"]).days
    return giorni_passati - container["intervallo"]


def mood(ritardo: int) -> tuple[str, str]:
    if ritardo <= 0:
        return "🌿", "sto bene"
    if ritardo <= 2:
        return "😐", "ho un po' sete"
    if ritardo <= 4:
        return "🥀", "sto appassendo, dai"
    return "💀", "mi hai abbandonato"


async def get_weather_adjustment() -> dict:
    """Pioggia e temp massima di ieri a Cormano (Open-Meteo, no API key)."""
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get("https://api.open-meteo.com/v1/forecast", params={
                "latitude": LAT, "longitude": LON,
                "daily": "precipitation_sum,temperature_2m_max",
                "past_days": 1, "forecast_days": 1,
                "timezone": "Europe/Berlin",
            })
        daily = r.json().get("daily", {})
        pioggia = (daily.get("precipitation_sum") or [0])[0]
        temp_max = (daily.get("temperature_2m_max") or [0])[0]
        return {"pioggia_mm": pioggia or 0, "temp_max": temp_max or 0}
    except Exception:
        return {"pioggia_mm": 0, "temp_max": 0}


def effective_intervallo(container: dict, weather: dict) -> int:
    intervallo = container["intervallo"]
    if weather["temp_max"] > 30:
        intervallo = max(1, intervallo - 1)
    return intervallo


def prossimo_controllo(container: dict, weather: dict) -> date | None:
    """Data stimata del prossimo controllo (None se mai annaffiato)."""
    if container["ultimo"] is None:
        return None
    return container["ultimo"] + timedelta(days=effective_intervallo(container, weather))


def is_due(container: dict, oggi: date, hour: int, weather: dict) -> bool:
    """Piante coperte: pioggia leggera non conta, solo un acquazzone (>=5mm) ammorbidisce
    di mezza giornata (salta solo il controllo delle 8, non annulla la giornata intera)."""
    if container["ultimo"] is None:
        return False
    giorni_passati = (oggi - container["ultimo"]).days
    due = giorni_passati >= effective_intervallo(container, weather)
    if due and hour == 8 and weather["pioggia_mm"] >= 5:
        return False
    return due


TIPS = [
    "annaffia la terra, non le foglie — meno rischio funghi",
    "se vedi fiorellini spuntare in cima, staccali: il basilico fiorito diventa amaro",
    "raccogli dall'alto (sopra un nodo di foglie), mai spogliare una pianta intera — si ramifica meglio",
    "terra secca al tatto 2-3cm sotto la superficie = ha davvero sete, non fidarti solo delle foglie",
    "troppa acqua è peggio di poca: foglie basse gialle o macchie scure sui fusti = stai esagerando",
    "pianticine fitte tra loro? sfoltisci man mano che crescono, l'aria deve circolare",
    "non lasciare acqua ferma nel sottovaso dopo l'annaffiata — le radici marciscono",
    "giornata molto calda e afosa? un controllo visivo extra non fa male, oltre al reminder",
]


def _pick_tip(oggi: date) -> str:
    return TIPS[oggi.toordinal() % len(TIPS)]


def _prossimo_label(container: dict, weather: dict, oggi: date, dopo_annaffiata: bool = False) -> str:
    """Testo prossimo controllo. Se dopo_annaffiata, calcola come se annaffiassi oggi
    (usato nel reminder, dove si presume l'azione appena richiesta)."""
    if dopo_annaffiata:
        prossimo = oggi + timedelta(days=effective_intervallo(container, weather))
    else:
        prossimo = prossimo_controllo(container, weather)
        if prossimo is None:
            return ""
    delta = (prossimo - oggi).days
    if delta <= 0:
        return "prossimo controllo: oggi"
    return f"prossimo controllo: {prossimo.strftime('%d/%m')} (tra {delta}gg)"


def build_reminder(short: str, container: dict, oggi: date, weather: dict) -> dict:
    ritardo = giorni_ritardo(container, oggi) or 0
    emoji, testo = mood(ritardo)
    cfg = CONTAINERS[short]
    text = (f"{emoji} *{cfg['nome']}* ({container['piante']}): {testo}.\n"
            f"Annaffia fino a che esce dal foro di drenaggio (~{cfg['ml']}).\n"
            f"Se annaffi ora, {_prossimo_label(container, weather, oggi, dopo_annaffiata=True)}.")
    if container["streak"] >= 3:
        text += f"\n🔥 {container['streak']} volte di fila in orario."
    text += f"\n\n💡 _{_pick_tip(oggi)}_"
    markup = {"inline_keyboard": [[{"text": "✅ Annaffiato", "callback_data": f"pw:{short}"}]]}
    return {"text": text, "markup": markup}


async def status_report() -> str:
    oggi = datetime.now(ROME).date()
    containers = await get_all_containers()
    weather = await get_weather_adjustment()
    lines = ["🌱 *Stato piante*"]
    for c in containers:
        if c["ultimo"] is None:
            lines.append(f"\n⚪ *{c['nome']}* ({c['piante']}): non ancora avviato")
            continue
        ritardo = giorni_ritardo(c, oggi)
        emoji, testo = mood(ritardo)
        giorni_fa = (oggi - c["ultimo"]).days
        prossimo_txt = _prossimo_label(c, weather, oggi)
        lines.append(f"\n{emoji} *{c['nome']}* ({c['piante']}): {testo}\n"
                     f"ultima annaffiata {giorni_fa}gg fa ({c['ultimo'].strftime('%d/%m')}) · streak {c['streak']}\n"
                     f"{prossimo_txt}")
    return "\n".join(lines)


async def water_container(short: str) -> str:
    cfg = CONTAINERS.get(short)
    if not cfg:
        return "Contenitore sconosciuto."
    container = await _get_container(cfg["nome"])
    if not container:
        return f"Non trovo '{cfg['nome']}' su Notion."
    oggi = datetime.now(ROME).date()
    ritardo = giorni_ritardo(container, oggi)
    on_time = ritardo is None or ritardo <= 0
    nuovo_streak = container["streak"] + 1 if on_time else 1
    async with httpx.AsyncClient(timeout=10) as client:
        await client.patch(f"https://api.notion.com/v1/pages/{container['id']}",
            headers=HEADERS, json={"properties": {
                "UltimoAnnaffiato": {"date": {"start": oggi.isoformat()}},
                "Streak": {"number": nuovo_streak},
            }})
    streak_line = f"\n🔥 Streak: {nuovo_streak}" if nuovo_streak >= 2 else ""
    return f"✅ {cfg['nome']} annaffiata. Prossimo controllo tra {container['intervallo']} giorni.{streak_line}"
