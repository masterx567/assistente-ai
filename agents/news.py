import httpx
import os
import xml.etree.ElementTree as ET
from datetime import datetime
from agents.calendar import get_today_events
from agents.budget import get_budget_alerts, format_alerts

FILTERS = {
    "ai":       ["intelligenza artificiale", "chatgpt", "openai", "anthropic", "llm", "machine learning", "deep learning", "gemini", "copilot", "claude", "modello ai", "robot", " ai "],
    "tech":     ["apple", "google", "microsoft", "meta", "smartphone", "app ", "software", "hardware", "iphone", "android", "chip", "processore", "nvidia", "amd"],
    "politica": ["governo", "parlamento", "senato", "camera", "meloni", "elezioni", "partito", "ministro", "decreto", "legge", "pd ", "lega ", "m5s", "fratelli d'italia"],
    "finanza":  ["borsa", "mercati", "inflazione", "pil", "spread", "bce", "banca", "azioni", "investimenti", "euro", "dollaro", "petrolio", "tassi", "titoli"],
}

RSS_FEEDS = [
    ("https://www.ansa.it/sito/notizie/tecnologia/tecnologia_rss.xml", ["ai", "tech"]),
    ("https://www.ansa.it/sito/notizie/politica/politica_rss.xml", ["politica"]),
    ("https://www.ansa.it/sito/notizie/economia/economia_rss.xml", ["finanza"]),
    ("https://www.wired.it/rss", ["ai", "tech"]),
]


def _parse_rss(xml_text: str) -> list[dict]:
    try:
        root = ET.fromstring(xml_text)
        items = []
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            if title and link and "[Removed]" not in title:
                items.append({"title": title, "url": link})
        return items
    except Exception:
        return []


async def get_morning_briefing() -> str:
    lines = [f"🌅 *Briefing {datetime.now().strftime('%d/%m/%Y')}*\n"]

    # 1. Impegni di oggi
    today_events = await get_today_events()
    lines.append("📅 *Impegni di oggi*")
    lines.append(today_events if today_events else "Nessun impegno.")
    lines.append("")

    # 2. Notizie RSS
    lines.append("📰 *Notizie importanti*")

    ai_articles: list = []
    tech_articles: list = []
    pol_articles: list = []
    fin_articles: list = []

    buckets = {"ai": ai_articles, "tech": tech_articles, "politica": pol_articles, "finanza": fin_articles}

    async with httpx.AsyncClient(timeout=15) as client:
        for url, categories in RSS_FEEDS:
            try:
                r = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
                items = _parse_rss(r.text) if r.status_code == 200 else []
            except Exception:
                items = []

            for item in items:
                t_lower = item["title"].lower()
                for cat in categories:
                    if any(kw in t_lower for kw in FILTERS[cat]):
                        buckets[cat].append(item)
                        break

    sections = [
        ("🤖 AI", ai_articles),
        ("🏛️ Politica", pol_articles),
        ("💹 Finanza", fin_articles),
        ("💻 Tecnologia", tech_articles),
    ]

    seen = set()
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

    lines.append("")

    # 3. Budget alert
    alerts = await get_budget_alerts()
    if alerts:
        lines.append("💸 *Categorie oltre budget*")
        lines.append(format_alerts(alerts))

    return "\n".join(lines)
