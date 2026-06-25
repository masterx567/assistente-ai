import httpx
import os
import xml.etree.ElementTree as ET
from datetime import datetime
from agents.calendar import get_today_events
from agents.budget import get_budget_alerts, format_alerts

AI_KW = ["intelligenza artificiale", "ai ", " ai,", "chatgpt", "openai", "anthropic", "llm", "machine learning", "deep learning", "gemini", "copilot"]

RSS_FEEDS = [
    ("https://www.ansa.it/sito/notizie/tecnologia/tecnologia_rss.xml", "tech"),
    ("https://www.ansa.it/sito/notizie/politica/politica_rss.xml", "politica"),
    ("https://www.ansa.it/sito/notizie/economia/economia_rss.xml", "finanza"),
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

    ai_articles = []
    tech_articles = []
    pol_articles = []
    fin_articles = []

    async with httpx.AsyncClient(timeout=15) as client:
        for url, category in RSS_FEEDS:
            try:
                r = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
                items = _parse_rss(r.text) if r.status_code == 200 else []
            except Exception:
                items = []

            for item in items:
                t_lower = item["title"].lower()
                if category == "tech":
                    if any(kw in t_lower for kw in AI_KW):
                        ai_articles.append(item)
                    else:
                        tech_articles.append(item)
                elif category == "politica":
                    pol_articles.append(item)
                elif category == "finanza":
                    fin_articles.append(item)

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
