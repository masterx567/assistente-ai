import os
import httpx
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

ICAL_URL = os.getenv("GOOGLE_CALENDAR_ICAL_URL")
ROME = ZoneInfo("Europe/Rome")


async def get_events(days_ahead: int = 7) -> list[dict]:
    if not ICAL_URL:
        return []
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(ICAL_URL)
    if r.status_code != 200:
        return []

    events = []
    today = date.today()
    end = today + timedelta(days=days_ahead)

    lines = r.text.splitlines()
    current = {}
    in_event = False

    for line in lines:
        if line == "BEGIN:VEVENT":
            in_event = True
            current = {}
        elif line == "END:VEVENT" and in_event:
            in_event = False
            ev_date = current.get("date")
            if ev_date and today <= ev_date <= end:
                events.append(current)
        elif in_event:
            if line.startswith("SUMMARY:"):
                current["title"] = line[8:]
            elif line.startswith("DTSTART"):
                val = line.split(":")[-1]
                try:
                    if "T" in val:
                        dt = datetime.strptime(val[:15], "%Y%m%dT%H%M%S")
                        if "Z" in val:
                            from zoneinfo import ZoneInfo as ZI
                            dt = dt.replace(tzinfo=ZI("UTC")).astimezone(ROME)
                        current["date"] = dt.date()
                        current["time"] = dt.strftime("%H:%M")
                    else:
                        current["date"] = datetime.strptime(val[:8], "%Y%m%d").date()
                        current["time"] = None
                except Exception:
                    pass
            elif line.startswith("LOCATION:"):
                current["location"] = line[9:]

    events.sort(key=lambda e: e["date"])
    return events


def format_events(events: list[dict], days_ahead: int = 7) -> str:
    if not events:
        return f"📅 Nessun impegno nei prossimi {days_ahead} giorni."

    today = date.today()
    lines = ["📅 *I tuoi prossimi impegni:*\n"]

    for ev in events:
        d = ev["date"]
        if d == today:
            day_label = "Oggi"
        elif d == today + timedelta(days=1):
            day_label = "Domani"
        else:
            day_label = d.strftime("%A %d/%m")

        time_str = f" alle {ev['time']}" if ev.get("time") else ""
        loc_str = f" — {ev['location']}" if ev.get("location") else ""
        lines.append(f"• *{day_label}*{time_str}: {ev['title']}{loc_str}")

    return "\n".join(lines)


async def get_today_events() -> str:
    events = await get_events(days_ahead=0)
    if not events:
        return ""
    lines = ["📅 *Oggi:*"]
    for ev in events:
        time_str = f" {ev['time']}" if ev.get("time") else ""
        lines.append(f"• {ev['title']}{time_str}")
    return "\n".join(lines)
