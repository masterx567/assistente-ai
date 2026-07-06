import httpx
import os
from datetime import datetime, date

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
DB_STUDIO = "fc364630-38a7-4167-8034-caf0155e8f12"

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}


async def get_next_course() -> dict | None:
    """Prossimo corso da_fare, ordinato per 'ordine'."""
    body = {
        "filter": {"property": "stato", "select": {"equals": "da_fare"}},
        "sorts": [{"property": "ordine", "direction": "ascending"}],
        "page_size": 1,
    }
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(f"https://api.notion.com/v1/databases/{DB_STUDIO}/query", headers=HEADERS, json=body)
    results = r.json().get("results", [])
    if not results:
        return None
    page = results[0]
    props = page["properties"]
    name_parts = props.get("Name", {}).get("title", [])
    name = name_parts[0]["plain_text"] if name_parts else "?"
    fine_iso = (props.get("fine", {}).get("date") or {}).get("start", "")[:10]
    return {"id": page["id"], "corso": name, "fine": fine_iso}


async def mark_course_done(course_id: str) -> None:
    async with httpx.AsyncClient(timeout=10) as client:
        await client.patch(f"https://api.notion.com/v1/pages/{course_id}", headers=HEADERS, json={
            "properties": {"stato": {"select": {"name": "completato"}}}
        })


def format_next_course_line(course: dict | None) -> str:
    if not course:
        return ""
    fine = date.fromisoformat(course["fine"]).strftime("%d/%m/%Y") if course["fine"] else "n/d"
    return f"\n📚 *Prossimo:* {course['corso']} — entro {fine}"


def is_overdue(course: dict) -> bool:
    if not course.get("fine"):
        return False
    return date.today() >= date.fromisoformat(course["fine"])


async def get_full_plan() -> list[dict]:
    """Tutti i corsi ordinati per 'ordine', con stato e data prevista."""
    body = {
        "sorts": [{"property": "ordine", "direction": "ascending"}],
        "page_size": 100,
    }
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(f"https://api.notion.com/v1/databases/{DB_STUDIO}/query", headers=HEADERS, json=body)
    courses = []
    for page in r.json().get("results", []):
        props = page["properties"]
        name_parts = props.get("Name", {}).get("title", [])
        name = name_parts[0]["plain_text"] if name_parts else "?"
        fine_iso = (props.get("fine", {}).get("date") or {}).get("start", "")[:10]
        stato = (props.get("stato", {}).get("select") or {}).get("name", "da_fare")
        courses.append({"corso": name, "fine": fine_iso, "stato": stato})
    return courses


def format_study_plan(courses: list[dict]) -> str:
    if not courses:
        return "Nessun corso nel piano di studio."
    lines = ["🎓 *Piano di studio*\n"]
    for c in courses:
        emoji = "✅" if c["stato"] == "completato" else "📖"
        fine = date.fromisoformat(c["fine"]).strftime("%d/%m/%Y") if c["fine"] else "n/d"
        lines.append(f"{emoji} {c['corso']} — {fine}")
    done = sum(1 for c in courses if c["stato"] == "completato")
    lines.append(f"\n*{done}/{len(courses)} completati*")
    return "\n".join(lines)
