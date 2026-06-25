import httpx
import os
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone, date
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo
from agents.calendar import get_today_events
from agents.budget import get_budget_alerts, format_alerts

ROME = ZoneInfo("Europe/Rome")

FILTERS = {
    "ai":       ["intelligenza artificiale", "chatgpt", "openai", "anthropic", "llm", "machine learning",
                 "deep learning", "gemini", "copilot", "claude", "modello ai", "robot", " ai ", "gpt",
                 "neural", "algoritmo", "automazione", "ai.", "ia ", "ia,"],
    "tech":     ["apple", "google", "microsoft", "meta", "smartphone", "software", "hardware",
                 "iphone", "android", "chip", "processore", "nvidia", "amd", "samsung", "tesla",
                 "tech", "digitale", "cybersicurezza", "hacker", "startup", "silicon"],
    "politica": ["governo", "parlamento", "senato", "camera", "meloni", "elezioni", "partito",
                 "ministro", "decreto", "legge", "pd ", "lega ", "m5s", "fratelli", "politica",
                 "premier", "presidente", "voto", "coalizione", "opposizione"],
    "finanza":  ["borsa", "mercati", "inflazione", "pil", "spread", "bce", "banca", "azioni",
                 "investimenti", "euro", "dollaro", "petrolio", "tassi", "titoli", "economia",
                 "finanza", "ftse", "nasdaq", "wall street", "recessione", "crescita"],
}

# (url, categorie_keyword, categoria_fallback_se_nessun_match)
RSS_FEEDS = [
    ("https://www.ansa.it/sito/notizie/tecnologia/tecnologia_rss.xml", ["ai", "tech"], "tech"),
    ("https://www.ansa.it/sito/notizie/politica/politica_rss.xml", ["politica"], "politica"),
    ("https://www.ansa.it/sito/notizie/economia/economia_rss.xml", ["finanza"], "finanza"),
    ("https://www.corriere.it/rss/economia.xml", ["finanza"], "finanza"),
    ("https://www.corriere.it/rss/tecnologia.xml", ["ai", "tech"], "tech"),
    ("https://punto-informatico.it/feed/", ["ai", "tech"], "tech"),
    ("https://www.hdblog.it/rss/", ["ai", "tech"], "tech"),
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

    ai_articles: list = []
    tech_articles: list = []
    pol_articles: list = []
    fin_articles: list = []
    buckets = {"ai": ai_articles, "tech": tech_articles, "politica": pol_articles, "finanza": fin_articles}

    async with httpx.AsyncClient(timeout=15) as client:
        for url, categories, fallback_cat in RSS_FEEDS:
            try:
                r = await client.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
                items = _parse_rss(r.text) if r.status_code == 200 else []
            except Exception:
                items = []

            for item in items:
                t_lower = item["title"].lower()
                matched = False
                for cat in categories:
                    if any(kw in t_lower for kw in FILTERS[cat]):
                        buckets[cat].append(item)
                        matched = True
                        break
                # fallback: se nessuna keyword match, metti nella categoria principale del feed
                if not matched and fallback_cat:
                    buckets[fallback_cat].append(item)

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
