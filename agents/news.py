import httpx
import os
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone, date
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo
from agents.calendar import get_today_events
from agents.budget import get_budget_alerts, format_alerts

ROME = ZoneInfo("Europe/Rome")

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
        ("🤖 AI", ai_articles),
        ("🏛️ Politica", pol_articles),
        ("💹 Finanza", fin_articles),
        ("💻 Tecnologia", tech_articles),
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
            section_lines.append(f"  • [{a['title']}]({a['url']})")
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

    return "\n".join(lines)
