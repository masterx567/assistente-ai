import os
import httpx
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

ICAL_URL = os.getenv("GOOGLE_CALENDAR_ICAL_URL")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REFRESH_TOKEN = os.getenv("GOOGLE_REFRESH_TOKEN")
ROME = ZoneInfo("Europe/Rome")
CALENDAR_ID = "primary"


async def _get_access_token() -> str | None:
    if not all([GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN]):
        return None
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.post("https://oauth2.googleapis.com/token", data={
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "refresh_token": GOOGLE_REFRESH_TOKEN,
            "grant_type": "refresh_token",
        })
    return r.json().get("access_token")


async def add_event(title: str, start_dt: datetime, end_dt: datetime = None) -> str:
    token = await _get_access_token()
    if not token:
        return "Credenziali Google Calendar non configurate."

    if end_dt is None:
        end_dt = start_dt + timedelta(hours=1)

    fmt = "%Y-%m-%dT%H:%M:%S"
    tz = "Europe/Rome"

    body = {
        "summary": title,
        "start": {"dateTime": start_dt.strftime(fmt), "timeZone": tz},
        "end": {"dateTime": end_dt.strftime(fmt), "timeZone": tz},
    }

    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.post(
            f"https://www.googleapis.com/calendar/v3/calendars/{CALENDAR_ID}/events",
            headers={"Authorization": f"Bearer {token}"},
            json=body,
        )

    if r.status_code in (200, 201):
        ev = r.json()
        day = start_dt.strftime("%d/%m")
        time = start_dt.strftime("%H:%M")
        return f"✅ Aggiunto: *{title}* — {day} alle {time}"
    return f"Errore creazione evento: {r.status_code}"


async def rename_event(old_title: str, new_title: str) -> str:
    token = await _get_access_token()
    if not token:
        return "Credenziali Google Calendar non configurate."

    now = datetime.now(ROME).strftime("%Y-%m-%dT%H:%M:%SZ")
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(
            f"https://www.googleapis.com/calendar/v3/calendars/{CALENDAR_ID}/events",
            headers={"Authorization": f"Bearer {token}"},
            params={"q": old_title, "timeMin": now, "maxResults": 5, "singleEvents": True},
        )

    items = r.json().get("items", [])
    if not items:
        return f"Nessun evento trovato con '{old_title}'."

    ev = items[0]
    ev_id = ev["id"]

    async with httpx.AsyncClient(timeout=10) as c:
        r2 = await c.patch(
            f"https://www.googleapis.com/calendar/v3/calendars/{CALENDAR_ID}/events/{ev_id}",
            headers={"Authorization": f"Bearer {token}"},
            json={"summary": new_title},
        )

    if r2.status_code == 200:
        return f"✏️ Rinominato: *{old_title}* → *{new_title}*"
    return f"Errore rinomina: {r2.status_code}"


async def reschedule_event(title_fragment: str, new_date: str, new_time: str) -> str:
    token = await _get_access_token()
    if not token:
        return "Credenziali Google Calendar non configurate."

    now = datetime.now(ROME).strftime("%Y-%m-%dT%H:%M:%SZ")
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(
            f"https://www.googleapis.com/calendar/v3/calendars/{CALENDAR_ID}/events",
            headers={"Authorization": f"Bearer {token}"},
            params={"q": title_fragment, "timeMin": now, "maxResults": 5, "singleEvents": True},
        )

    items = r.json().get("items", [])
    if not items:
        return f"Nessun evento trovato con '{title_fragment}'."

    ev = items[0]
    ev_id = ev["id"]
    ev_title = ev.get("summary", title_fragment)

    new_start = datetime.strptime(f"{new_date} {new_time}", "%Y-%m-%d %H:%M").replace(tzinfo=ROME)
    new_end = new_start + timedelta(hours=1)
    fmt = "%Y-%m-%dT%H:%M:%S"
    tz = "Europe/Rome"

    async with httpx.AsyncClient(timeout=10) as c:
        r2 = await c.patch(
            f"https://www.googleapis.com/calendar/v3/calendars/{CALENDAR_ID}/events/{ev_id}",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "start": {"dateTime": new_start.strftime(fmt), "timeZone": tz},
                "end": {"dateTime": new_end.strftime(fmt), "timeZone": tz},
            },
        )

    if r2.status_code == 200:
        return f"🕐 Spostato: *{ev_title}* → {new_start.strftime('%d/%m alle %H:%M')}"
    return f"Errore spostamento: {r2.status_code}"


async def delete_event_by_title(title_fragment: str) -> str:
    token = await _get_access_token()
    if not token:
        return "Credenziali Google Calendar non configurate."

    now = datetime.now(ROME).strftime("%Y-%m-%dT%H:%M:%SZ")
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(
            f"https://www.googleapis.com/calendar/v3/calendars/{CALENDAR_ID}/events",
            headers={"Authorization": f"Bearer {token}"},
            params={"q": title_fragment, "timeMin": now, "maxResults": 5, "singleEvents": True},
        )

    items = r.json().get("items", [])
    if not items:
        return f"Nessun evento trovato con '{title_fragment}'."

    ev = items[0]
    ev_id = ev["id"]
    ev_title = ev.get("summary", title_fragment)

    async with httpx.AsyncClient(timeout=10) as c:
        r2 = await c.delete(
            f"https://www.googleapis.com/calendar/v3/calendars/{CALENDAR_ID}/events/{ev_id}",
            headers={"Authorization": f"Bearer {token}"},
        )

    if r2.status_code == 204:
        return f"🗑️ Eliminato: *{ev_title}*"
    return f"Errore eliminazione: {r2.status_code}"


async def search_events(query: str, days_ahead: int = 365) -> list[dict]:
    """Cerca eventi per titolo nei prossimi N giorni via Google Calendar API."""
    token = await _get_access_token()
    if not token:
        return []
    now = datetime.now(ROME)
    time_max = now + timedelta(days=days_ahead)
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(
            f"https://www.googleapis.com/calendar/v3/calendars/{CALENDAR_ID}/events",
            headers={"Authorization": f"Bearer {token}"},
            params={
                "q": query,
                "timeMin": now.isoformat(),
                "timeMax": time_max.isoformat(),
                "singleEvents": True,
                "orderBy": "startTime",
                "maxResults": 20,
            },
        )
    results = []
    for item in r.json().get("items", []):
        start = item.get("start", {})
        dt_str = start.get("dateTime") or start.get("date")
        if not dt_str:
            continue
        try:
            if "T" in dt_str:
                dt = datetime.fromisoformat(dt_str).astimezone(ROME)
                time_str = dt.strftime("%H:%M")
            else:
                dt = datetime.fromisoformat(dt_str).replace(tzinfo=ROME)
                time_str = None
            results.append({"title": item.get("summary", ""), "date": dt.date(), "time": time_str})
        except Exception:
            pass
    return results


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
                            dt = dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(ROME)
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
    events = await get_events(days_ahead=1)
    if not events:
        return ""
    today = date.today()
    tomorrow = today + timedelta(days=1)
    today_evs = [e for e in events if e["date"] == today]
    tomorrow_evs = [e for e in events if e["date"] == tomorrow]
    DAYS_IT = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]

    lines = []
    if today_evs:
        day_name = DAYS_IT[today.weekday()]
        lines.append(f"*Oggi — {day_name} {today.strftime('%d/%m')}*")
        for ev in today_evs:
            time_str = f" alle {ev['time']}" if ev.get("time") else ""
            lines.append(f"  📌 {ev['title']}{time_str}")
    if tomorrow_evs:
        day_name = DAYS_IT[tomorrow.weekday()]
        lines.append(f"*Domani — {day_name} {tomorrow.strftime('%d/%m')}*")
        for ev in tomorrow_evs:
            time_str = f" alle {ev['time']}" if ev.get("time") else ""
            lines.append(f"  📌 {ev['title']}{time_str}")
    return "\n".join(lines) if lines else ""
