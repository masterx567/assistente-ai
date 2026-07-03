import httpx
import os
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone, date
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo
from agents.calendar import get_today_events
from agents.budget import get_budget_alerts, format_alerts
from agents.studio import get_next_course, format_next_course_line, is_overdue
from agents.pending import save_pending, get_pending

ROME = ZoneInfo("Europe/Rome")

_WEATHER_IT = {
    "113": "soleggiato", "116": "parzialmente nuvoloso", "119": "nuvoloso", "122": "coperto",
    "143": "nebbia", "248": "nebbia", "260": "nebbia ghiacciata",
    "176": "pioggia leggera", "179": "neve leggera", "182": "pioggia mista a neve",
    "185": "pioggerella ghiacciata", "200": "temporale locale",
    "227": "neve con vento", "230": "bufera di neve",
    "263": "pioggerella leggera", "266": "pioggerella",
    "281": "pioggerella ghiacciata", "284": "pioggerella ghiacciata",
    "293": "pioggia leggera", "296": "pioggia leggera", "299": "pioggia moderata",
    "302": "pioggia moderata", "305": "pioggia intensa", "308": "pioggia intensa",
    "311": "pioggerella ghiacciata", "314": "pioggerella ghiacciata",
    "317": "pioggia mista a neve", "320": "pioggia mista a neve",
    "323": "neve leggera", "326": "neve leggera", "329": "neve moderata",
    "332": "neve moderata", "335": "neve intensa", "338": "neve intensa",
    "350": "grandine", "353": "pioggerella", "356": "pioggia intensa",
    "359": "pioggia torrenziale", "362": "pioggia mista a neve",
    "365": "pioggia mista a neve", "368": "neve leggera", "371": "neve intensa",
    "374": "grandine leggera", "377": "grandine",
    "386": "temporale con pioggia", "389": "temporale con pioggia intensa",
    "392": "temporale con neve", "395": "bufera di neve con tuoni",
}

GN = "https://news.google.com/rss/search?hl=it&gl=IT&ceid=IT:it&q="

# (url, bucket, usa_fallback)  — Google News RSS per topic specifici
RSS_FEEDS = [
    (GN + "intelligenza+artificiale+OR+ChatGPT+OR+OpenAI", "ai", True),
    (GN + "politica+italiana+OR+governo+Meloni+OR+parlamento", "politica", True),
    (GN + "borsa+Milano+OR+mercati+finanziari+OR+economia+italiana", "finanza", True),
    (GN + "tecnologia+smartphone+OR+Apple+OR+Google+OR+Microsoft", "tech", True),
    ("https://www.hdblog.it/rss/", "tech", True),
    ("https://www.ansa.it/sito/notizie/politica/politica_rss.xml", "politica", True),
    ("https://www.ansa.it/sito/notizie/economia/economia_rss.xml", "finanza", True),
]


def _parse_rss(xml_text: str, max_age_hours: int = 48) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    try:
        root = ET.fromstring(xml_text)
        items = []
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            pub_date = item.findtext("pubDate") or ""
            if not title or not link or "[Removed]" in title:
                continue
            if pub_date:
                try:
                    dt = parsedate_to_datetime(pub_date)
                    if dt < cutoff:
                        continue
                except Exception:
                    pass
            items.append({"title": title, "url": link})
        return items
    except Exception:
        return []


async def get_morning_briefing() -> str:
    now = datetime.now(ROME)
    today = date.today()
    tomorrow = today + timedelta(days=1)
    lines = [f"🌅 *Buongiorno! Briefing del {now.strftime('%d/%m/%Y')}*\n"]

    # 0. Meteo
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            w = await client.get("https://wttr.in/Milano?lang=it&format=j1", headers={"User-Agent": "curl/7.0"})
        if w.status_code == 200:
            wj = w.json()
            cur = wj["current_condition"][0]
            temp = cur["temp_C"]
            code = cur.get("weatherCode", "")
            desc = _WEATHER_IT.get(str(code), cur["weatherDesc"][0]["value"])
            feels = cur["FeelsLikeC"]
            lines.append(f"🌤️ *Milano* — {temp}°C, percepita {feels}°C, {desc}")
            # Previsioni domani e dopodomani
            forecast = wj.get("weather", [])
            day_names = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"]
            forecast_lines = []
            for day in forecast[1:3]:
                try:
                    d = datetime.strptime(day["date"], "%Y-%m-%d")
                    hourly = day.get("hourly", [])
                    mid = hourly[4] if len(hourly) > 4 else (hourly[-1] if hourly else {})
                    fc_code = mid.get("weatherCode", "")
                    fc_desc = _WEATHER_IT.get(str(fc_code), "")
                    fc_max = day["maxtempC"]
                    fc_min = day["mintempC"]
                    forecast_lines.append(f"  {day_names[d.weekday()]}: {fc_min}°-{fc_max}°C {fc_desc}")
                except Exception:
                    pass
            if forecast_lines:
                lines.extend(forecast_lines)
            lines.append("")
    except Exception:
        pass

    # 1. Impegni
    today_events = await get_today_events()
    lines.append("━━━━━━━━━━━━━━━")
    lines.append("📅 *AGENDA*")
    if today_events:
        lines.append(today_events)
    else:
        lines.append("_Nessun impegno oggi né domani_")
    lines.append("")

    # 2. Notizie RSS
    lines.append("━━━━━━━━━━━━━━━")
    lines.append("📰 *NOTIZIE*")

    buckets: dict = {"ai": [], "tech": [], "politica": [], "finanza": []}

    async with httpx.AsyncClient(timeout=15) as client:
        for url, bucket, _ in RSS_FEEDS:
            try:
                r = await client.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
                items = _parse_rss(r.text, max_age_hours=72) if r.status_code == 200 else []
            except Exception:
                items = []
            buckets[bucket].extend(items)

    sections = [
        ("🤖 AI", buckets["ai"]),
        ("🏛️ Politica", buckets["politica"]),
        ("💹 Finanza", buckets["finanza"]),
        ("💻 Tecnologia", buckets["tech"]),
    ]

    seen = set()
    any_news = False
    for label, articles in sections:
        count = 0
        section_lines = []
        for a in articles:
            if a["title"] in seen or count >= 2:
                continue
            seen.add(a["title"])
            section_lines.append(f"  • {a['title']}")
            count += 1
        if section_lines:
            lines.append(f"\n{label}")
            lines.extend(section_lines)
            any_news = True

    if not any_news:
        lines.append("_Nessuna notizia recente disponibile_")

    lines.append("")

    # 3. Budget alert
    alerts = await get_budget_alerts()
    if alerts:
        lines.append("━━━━━━━━━━━━━━━")
        lines.append("💸 *BUDGET*")
        lines.append(format_alerts(alerts))

    # 4. Piano di studio
    next_course = await get_next_course()
    if next_course:
        lines.append("━━━━━━━━━━━━━━━")
        lines.append("🎓 *STUDIO*" + format_next_course_line(next_course))
        if is_overdue(next_course) and not await get_pending():
            await save_pending("exam_done", {"course_id": next_course["id"], "corso": next_course["corso"]})
            lines.append(f"\nHai completato *{next_course['corso']}*? Rispondi sì o no.")

    return "\n".join(lines)
