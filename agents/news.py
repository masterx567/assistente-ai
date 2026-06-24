import httpx
import os
from datetime import datetime

NEWS_API_KEY = os.getenv("NEWS_API_KEY")


async def get_morning_briefing(topics: list[str] = None) -> str:
    """Fetch top Italian news + optional topics."""
    if topics is None:
        topics = ["tecnologia", "economia"]

    articles = []

    async with httpx.AsyncClient() as client:
        # Top news Italia
        r = await client.get(
            "https://newsapi.org/v2/top-headlines",
            params={
                "country": "it",
                "pageSize": 5,
                "apiKey": NEWS_API_KEY,
            },
        )
        if r.status_code == 200:
            articles.extend(r.json().get("articles", []))

        # Topic specifici
        for topic in topics[:2]:
            r = await client.get(
                "https://newsapi.org/v2/everything",
                params={
                    "q": topic,
                    "language": "it",
                    "sortBy": "publishedAt",
                    "pageSize": 3,
                    "apiKey": NEWS_API_KEY,
                },
            )
            if r.status_code == 200:
                articles.extend(r.json().get("articles", []))

    if not articles:
        return "Nessuna notizia disponibile al momento."

    lines = [f"📰 *Briefing del {datetime.now().strftime('%d/%m/%Y')}*\n"]
    seen = set()
    count = 0
    for a in articles:
        title = a.get("title", "")
        if not title or title in seen or "[Removed]" in title:
            continue
        seen.add(title)
        source = a.get("source", {}).get("name", "")
        lines.append(f"• {title} _{source}_")
        count += 1
        if count >= 7:
            break

    return "\n".join(lines)
