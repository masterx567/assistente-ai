import httpx
import os
from datetime import datetime
from agents.calendar import get_today_events
from agents.budget import get_budget_alerts, format_alerts

NEWS_API_KEY = os.getenv("NEWS_API_KEY")

TOPICS = [
    ("intelligenza artificiale OR AI OR ChatGPT", "🤖 AI"),
    ("politica italiana OR governo italiano", "🏛️ Politica"),
    ("finanza OR mercati OR economia OR borsa", "💹 Finanza"),
    ("tecnologia OR tech OR startup", "💻 Tecnologia"),
]


async def get_morning_briefing() -> str:
    lines = [f"🌅 *Briefing {datetime.now().strftime('%d/%m/%Y')}*\n"]

    # 1. Impegni di oggi
    today_events = await get_today_events()
    if today_events:
        lines.append("📅 *Impegni di oggi*")
        lines.append(today_events)
    else:
        lines.append("📅 *Impegni di oggi*\nNessun impegno.")

    lines.append("")

    # 2. Notizie per topic
    lines.append("📰 *Notizie importanti*")
    seen = set()

    async with httpx.AsyncClient(timeout=15) as client:
        for query, label in TOPICS:
            r = await client.get(
                "https://newsapi.org/v2/everything",
                params={
                    "q": query,
                    "language": "it",
                    "sortBy": "publishedAt",
                    "pageSize": 2,
                    "apiKey": NEWS_API_KEY,
                },
            )
            if r.status_code != 200:
                continue
            articles = r.json().get("articles", [])
            topic_lines = []
            for a in articles:
                title = a.get("title", "")
                if not title or title in seen or "[Removed]" in title:
                    continue
                seen.add(title)
                topic_lines.append(f"  • {title}")
            if topic_lines:
                lines.append(f"\n{label}")
                lines.extend(topic_lines)

    lines.append("")

    # 3. Budget alert
    alerts = await get_budget_alerts()
    if alerts:
        lines.append("💸 *Categorie oltre budget*")
        lines.append(format_alerts(alerts))

    return "\n".join(lines)
