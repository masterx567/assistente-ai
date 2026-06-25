import os
import asyncio
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from flask import Flask, request, jsonify
from dotenv import load_dotenv
import httpx

load_dotenv()

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from router import route_message
from agents.news import get_morning_briefing
from agents.budget import get_budget_alerts, format_alerts, get_monthly_spending, get_weekly_spending, format_spending_summary, format_weekly_summary
from agents.reminders import get_pending_reminders, mark_sent

app = Flask(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REFRESH_TOKEN = os.getenv("GOOGLE_REFRESH_TOKEN")
ROME = ZoneInfo("Europe/Rome")


def send_telegram(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    with httpx.Client(timeout=9) as c:
        r = c.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"})
        if not r.json().get("ok"):
            # Markdown fallisce → riprova senza formattazione
            c.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text})


def get_access_token() -> str | None:
    if not all([GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN]):
        return None
    r = httpx.post("https://oauth2.googleapis.com/token", data={
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "refresh_token": GOOGLE_REFRESH_TOKEN,
        "grant_type": "refresh_token",
    }, timeout=10)
    return r.json().get("access_token")


def get_upcoming_events(hours_ahead: int = 48) -> list[dict]:
    token = get_access_token()
    if not token:
        return []
    now = datetime.now(ROME)
    time_max = now + timedelta(hours=hours_ahead)
    r = httpx.get(
        "https://www.googleapis.com/calendar/v3/calendars/primary/events",
        headers={"Authorization": f"Bearer {token}"},
        params={
            "timeMin": now.isoformat(),
            "timeMax": time_max.isoformat(),
            "singleEvents": True,
            "orderBy": "startTime",
            "maxResults": 20,
        },
        timeout=10,
    )
    events = []
    for item in r.json().get("items", []):
        start = item.get("start", {})
        dt_str = start.get("dateTime") or start.get("date")
        if not dt_str:
            continue
        try:
            if "T" in dt_str:
                dt = datetime.fromisoformat(dt_str).astimezone(ROME)
            else:
                dt = datetime.fromisoformat(dt_str).replace(tzinfo=ROME)
            events.append({"title": item.get("summary", "Evento"), "start": dt})
        except Exception:
            pass
    return events


@app.route("/")
def root():
    return jsonify({"status": "ok"})


@app.route("/api/debug")
def debug():
    import router as r_module
    import inspect
    src = inspect.getsource(r_module.route_message)
    return jsonify({"router_keywords": src[:500], "ical": os.getenv("GOOGLE_CALENDAR_ICAL_URL", "NOT SET")[:50]})


@app.route("/api/webhook", methods=["POST"])
def webhook():
    data = request.get_json(silent=True) or {}
    message = data.get("message", {})
    chat_id = str(message.get("chat", {}).get("id", ""))
    text = message.get("text", "").strip()

    if text and chat_id == TELEGRAM_CHAT_ID:
        try:
            reply = asyncio.run(route_message(text))
        except Exception as e:
            reply = f"Errore: {str(e)}"
        send_telegram(reply)

    return jsonify({"ok": True})


@app.route("/api/test-webhook-full")
def test_webhook_full():
    """Simula webhook completo con 'ultime spese' + send_telegram."""
    import time
    t0 = time.time()
    text = "ultime spese"
    try:
        reply = asyncio.run(route_message(text))
        elapsed_route = round(time.time() - t0, 2)
        send_telegram(reply)
        elapsed_total = round(time.time() - t0, 2)
        return jsonify({"ok": True, "elapsed_route_s": elapsed_route, "elapsed_total_s": elapsed_total,
                        "reply_len": len(reply), "chat_id_env": TELEGRAM_CHAT_ID, "token_set": bool(TELEGRAM_TOKEN)})
    except Exception as e:
        return jsonify({"ok": False, "elapsed_s": round(time.time() - t0, 2), "error": str(e)})


@app.route("/api/morning")
def morning():
    briefing = asyncio.run(get_morning_briefing())
    send_telegram(briefing)
    return jsonify({"ok": True})


@app.route("/api/debug-news")
def debug_news():
    import xml.etree.ElementTree as ET
    feeds = [
        "https://www.ansa.it/sito/notizie/tecnologia/tecnologia_rss.xml",
        "https://www.corriere.it/rss/tecnologia.xml",
        "https://punto-informatico.it/feed/",
        "https://www.hdblog.it/rss/",
    ]
    result = {}
    with httpx.Client(timeout=10) as c:
        for url in feeds:
            try:
                r = c.get(url, headers={"User-Agent": "Mozilla/5.0"})
                root = ET.fromstring(r.text)
                titles = [(i.findtext("title",""), i.findtext("pubDate","")) for i in list(root.iter("item"))[:3]]
                result[url] = {"status": r.status_code, "items": titles}
            except Exception as e:
                result[url] = {"error": str(e)}
    return jsonify(result)


@app.route("/api/test-recent")
def test_recent():
    """Debug get_recent_transactions — bypassa routing."""
    import time
    t0 = time.time()
    try:
        from agents.budget import get_recent_transactions
        txs = asyncio.run(get_recent_transactions(5))
        elapsed = round(time.time() - t0, 2)
        return jsonify({"ok": True, "elapsed_s": elapsed, "count": len(txs), "data": txs})
    except Exception as e:
        elapsed = round(time.time() - t0, 2)
        return jsonify({"ok": False, "elapsed_s": elapsed, "error": str(e)})


@app.route("/api/test-route")
def test_route():
    """Debug routing — simula messaggio 'ultime spese'."""
    import time
    t0 = time.time()
    try:
        reply = asyncio.run(route_message("ultime spese"))
        elapsed = round(time.time() - t0, 2)
        return jsonify({"ok": True, "elapsed_s": elapsed, "reply": reply})
    except Exception as e:
        elapsed = round(time.time() - t0, 2)
        return jsonify({"ok": False, "elapsed_s": elapsed, "error": str(e)})


@app.route("/api/test-morning")
def test_morning():
    """Test manuale briefing — chiama questo per verificare che funzioni."""
    now = datetime.now(ROME)
    briefing = asyncio.run(get_morning_briefing())
    send_telegram(briefing)
    return jsonify({"ok": True, "time": now.strftime("%H:%M"), "sent": True})


@app.route("/api/evening")
def evening():
    alerts = asyncio.run(get_budget_alerts())
    if alerts:
        send_telegram(format_alerts(alerts))
    return jsonify({"ok": True})


@app.route("/api/tick")
def tick():
    """Job unico ogni 30 min — gestisce morning, evening e reminders."""
    now = datetime.now(ROME)
    h, m = now.hour, now.minute
    done = []

    # Briefing mattutino: 09:00–09:06 (finestra stretta, 1 tick max)
    if h == 9 and 0 <= m <= 4:
        briefing = asyncio.run(get_morning_briefing())
        send_telegram(briefing)
        done.append("morning")

    # Budget serale: 20:00–20:06
    if h == 20 and 0 <= m <= 4:
        alerts = asyncio.run(get_budget_alerts())
        if alerts:
            send_telegram(format_alerts(alerts))
        done.append("evening")

    # Riepilogo settimanale: domenica 20:00 (weekday==6)
    if now.weekday() == 6 and (h == 20 and m <= 15) or (now.weekday() == 6 and h == 19 and m >= 45):
        weekly = asyncio.run(get_weekly_spending())
        send_telegram(format_weekly_summary(weekly))
        done.append("weekly")

    # Riepilogo mensile: ultimo giorno del mese alle 20:00
    import calendar as cal_mod
    last_day = cal_mod.monthrange(now.year, now.month)[1]
    if now.day == last_day and ((h == 20 and m <= 15) or (h == 19 and m >= 45)):
        monthly = asyncio.run(get_monthly_spending())
        alerts = asyncio.run(get_budget_alerts())
        msg = f"📅 *Riepilogo {now.strftime('%B %Y')}*\n\n" + format_spending_summary(monthly)
        if alerts:
            msg += "\n\n" + format_alerts(alerts)
        send_telegram(msg)
        done.append("monthly")

    # Reminders eventi calendario
    done.extend(_check_reminders(now))

    # Promemoria Notion
    pending = asyncio.run(get_pending_reminders(now))
    for rem in pending:
        send_telegram(f"🔔 *{rem['text']}*")
        asyncio.run(mark_sent(rem["id"]))
        done.append(f"reminder:{rem['text']}")

    return jsonify({"ok": True, "done": done})


def _check_reminders(now: datetime) -> list[str]:
    events = get_upcoming_events(hours_ahead=26)
    sent = []
    h, m = now.hour, now.minute
    total_min = h * 60 + m

    for ev in events:
        start = ev["start"]
        title = ev["title"]
        minutes_until = (start - now).total_seconds() / 60

        # Giorno prima: 20:00–20:06
        tomorrow = (now + timedelta(days=1)).date()
        if start.date() == tomorrow and h == 20 and 0 <= m <= 4:
            send_telegram(f"📅 Domani alle *{start.strftime('%H:%M')}*: *{title}*")
            sent.append(f"day_before:{title}")

        # 2 ore prima: 118–124 min (finestra 6 min centrata su 120)
        elif 118 <= minutes_until <= 124:
            send_telegram(f"⏰ Tra 2 ore: *{title}* alle {start.strftime('%H:%M')}")
            sent.append(f"2h:{title}")

        # 1 ora prima: 58–64 min (finestra 6 min centrata su 60)
        elif 58 <= minutes_until <= 64:
            send_telegram(f"⏰ Tra 1 ora: *{title}* alle {start.strftime('%H:%M')}")
            sent.append(f"1h:{title}")


    return sent


@app.route("/api/reminders")
def reminders():
    now = datetime.now(ROME)
    events = get_upcoming_events(hours_ahead=26)
    sent = []

    for ev in events:
        start = ev["start"]
        title = ev["title"]
        minutes_until = (start - now).total_seconds() / 60

        # Giorno prima: notifica alle 20:00 ± 15 min
        tomorrow = (now + timedelta(days=1)).date()
        if start.date() == tomorrow and 19 * 60 + 45 <= now.hour * 60 + now.minute <= 20 * 60 + 15:
            day_str = start.strftime("%A %d/%m")
            time_str = start.strftime("%H:%M")
            send_telegram(f"📅 Domani alle *{time_str}*: *{title}*")
            sent.append(f"day_before:{title}")

        # 2 ore prima: 105–135 min
        elif 105 <= minutes_until <= 135:
            send_telegram(f"⏰ Tra 2 ore: *{title}* alle {start.strftime('%H:%M')}")
            sent.append(f"2h:{title}")

        # 1 ora prima: 45–75 min
        elif 45 <= minutes_until <= 75:
            send_telegram(f"⏰ Tra 1 ora: *{title}* alle {start.strftime('%H:%M')}")
            sent.append(f"1h:{title}")

    return jsonify({"ok": True, "sent": sent})
