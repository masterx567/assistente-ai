import httpx
import os
from datetime import date

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
DB_BOOTCAMP = "6d07e6be-6eeb-4fa2-b110-0ac89e08ad79"
SITE_URL = "https://daniele-acunzo.vercel.app/bootcamp"

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}

MODULI = ["GL", "SLA", "AP", "AR", "FA", "CLOSE"]


def _parse(page: dict) -> dict:
    props = page["properties"]
    title = props.get("Name", {}).get("title", [])
    name = title[0]["plain_text"] if title else "?"
    return {
        "id": page["id"],
        "nome": name,
        "codice": name.split(" ", 1)[0].upper(),
        "modulo": (props.get("modulo", {}).get("select") or {}).get("name", ""),
        "stato": (props.get("stato", {}).get("select") or {}).get("name", "da_fare"),
    }


async def get_lessons() -> list[dict]:
    """Tutte le lezioni ordinate per 'ordine' (64 < page_size 100)."""
    body = {"sorts": [{"property": "ordine", "direction": "ascending"}], "page_size": 100}
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(f"https://api.notion.com/v1/databases/{DB_BOOTCAMP}/query", headers=HEADERS, json=body)
    return [_parse(p) for p in r.json().get("results", [])]


def _lesson_line(lesson: dict | None) -> str:
    if not lesson:
        return "\n🎓 Bootcamp completato!"
    return f"\n📘 *Prossima:* {lesson['nome']}\n{SITE_URL}/{lesson['codice'].lower()}.html"


async def mark_lesson_done(codice: str) -> str:
    lessons = await get_lessons()
    codice = codice.upper()
    lesson = next((l for l in lessons if l["codice"] == codice), None)
    if not lesson:
        return f"Non trovo la lezione {codice} nel bootcamp."
    async with httpx.AsyncClient(timeout=10) as client:
        await client.patch(f"https://api.notion.com/v1/pages/{lesson['id']}", headers=HEADERS, json={
            "properties": {
                "stato": {"select": {"name": "completato"}},
                "completata_il": {"date": {"start": date.today().isoformat()}},
            }
        })
    lesson["stato"] = "completato"
    nxt = next((l for l in lessons if l["stato"] != "completato"), None)
    return f"✅ Lezione completata: *{lesson['nome']}*.{_lesson_line(nxt)}"


async def next_lesson() -> str:
    lessons = await get_lessons()
    nxt = next((l for l in lessons if l["stato"] != "completato"), None)
    return _lesson_line(nxt).strip()


async def progress() -> str:
    lessons = await get_lessons()
    if not lessons:
        return "Bootcamp vuoto."
    lines = ["🎓 *Bootcamp Oracle R12*\n"]
    for m in MODULI:
        mod = [l for l in lessons if l["modulo"] == m]
        done = sum(1 for l in mod if l["stato"] == "completato")
        lines.append(f"{'✅' if mod and done == len(mod) else '📖'} {m}: {done}/{len(mod)}")
    tot = sum(1 for l in lessons if l["stato"] == "completato")
    lines.append(f"\n*{tot}/{len(lessons)} lezioni*")
    nxt = next((l for l in lessons if l["stato"] != "completato"), None)
    lines.append(_lesson_line(nxt))
    return "\n".join(lines)
