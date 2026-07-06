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

from router import route_message, handle_checklist_toggle
from agents.errors import log_error
from agents.news import get_morning_briefing
from agents.budget import get_budget_alerts, format_alerts, get_monthly_spending, get_weekly_spending, format_spending_summary, format_weekly_summary, mese_anno_it, check_subscription_reminders, get_food_digest, format_food_digest, check_commitment_reminders, check_loan_reminders, get_spending_anomalies
from agents.reminders import get_pending_reminders, mark_sent
from agents.enable_banking import sync_transactions, session_expiry_days
from agents.pending import save_pending, already_ticked, mark_ticked
from agents.journal import get_streak_days, format_streak_message

app = Flask(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REFRESH_TOKEN = os.getenv("GOOGLE_REFRESH_TOKEN")
CRON_SECRET = os.getenv("CRON_SECRET")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")
ROME = ZoneInfo("Europe/Rome")


def _require_cron_secret():
    from flask import abort
    if not CRON_SECRET:
        abort(403)
    provided = request.args.get("secret") or \
        request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if provided != CRON_SECRET:
        abort(403)


def _chunk_text(text: str, limit: int = 4000) -> list[str]:
    """Spezza il testo in blocchi ≤limit, preferendo confini di paragrafo (\\n\\n)."""
    if len(text) <= limit:
        return [text]
    chunks = []
    current = ""
    for para in text.split("\n\n"):
        candidate = f"{current}\n\n{para}" if current else para
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            chunks.append(current)
        if len(para) <= limit:
            current = para
        else:
            for i in range(0, len(para), limit):
                chunks.append(para[i:i + limit])
            current = ""
    if current:
        chunks.append(current)
    return chunks


def send_telegram(text: str, reply_markup: dict = None):
    """Manda un messaggio Telegram. Se supera 4096 caratteri lo spezza in più invii
    (il limite dell'API), i bottoni (reply_markup) vanno solo sull'ultimo blocco."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    chunks = _chunk_text(text)
    with httpx.Client(timeout=9) as c:
        for i, chunk in enumerate(chunks):
            is_last = i == len(chunks) - 1
            payload = {"chat_id": TELEGRAM_CHAT_ID, "text": chunk, "parse_mode": "Markdown"}
            if reply_markup and is_last:
                payload["reply_markup"] = reply_markup
            r = c.post(url, json=payload)
            if not r.json().get("ok"):
                plain = {"chat_id": TELEGRAM_CHAT_ID, "text": chunk}
                if reply_markup and is_last:
                    plain["reply_markup"] = reply_markup
                c.post(url, json=plain)


def transcribe_voice(file_id: str, filename: str = "voice.ogg") -> str | None:
    """Scarica voce/video da Telegram e trascrive con Groq Whisper."""
    mime = "video/mp4" if filename.endswith(".mp4") else "audio/ogg"
    with httpx.Client(timeout=10) as c:
        r = c.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getFile", params={"file_id": file_id})
        file_path = r.json().get("result", {}).get("file_path")
        if not file_path:
            return None
        audio = c.get(f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}", timeout=10)
        if audio.status_code != 200:
            return None
    r2 = httpx.post(
        "https://api.groq.com/openai/v1/audio/transcriptions",
        headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
        files={"file": (filename, audio.content, mime)},
        data={"model": "whisper-large-v3-turbo", "language": "it"},
        timeout=15,
    )
    return r2.json().get("text", "").strip() or None


def answer_callback(callback_query_id: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery"
    with httpx.Client(timeout=5) as c:
        c.post(url, json={"callback_query_id": callback_query_id})


def edit_telegram_message(message_id: int, text: str, reply_markup: dict = None):
    """Modifica un messaggio esistente (usato per i bottoni checklist, evita spam di nuovi messaggi)."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/editMessageText"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "message_id": message_id, "text": text, "parse_mode": "Markdown"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    with httpx.Client(timeout=9) as c:
        r = c.post(url, json=payload)
        if not r.json().get("ok"):
            plain = {"chat_id": TELEGRAM_CHAT_ID, "message_id": message_id, "text": text}
            if reply_markup:
                plain["reply_markup"] = reply_markup
            c.post(url, json=plain)


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


@app.route("/callback")
def oauth_callback():
    code = request.args.get("code", "")
    state = request.args.get("state", "")
    full_url = request.url
    return (
        f"<h2>OAuth Callback</h2>"
        f"<p><b>Code:</b> <code>{code}</code></p>"
        f"<p><b>State:</b> <code>{state}</code></p>"
        f"<p><b>Full URL:</b> <code>{full_url}</code></p>",
        200,
    )


@app.route("/api/webhook", methods=["POST"])
def webhook():
    if WEBHOOK_SECRET:
        if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
            return jsonify({"ok": False}), 403
    data = request.get_json(silent=True) or {}

    # Gestione callback_query (tap su bottone inline, es. checklist viaggio)
    callback = data.get("callback_query")
    if callback:
        cb_chat_id = str(callback.get("message", {}).get("chat", {}).get("id", ""))
        cb_message_id = callback.get("message", {}).get("message_id")
        cb_data = callback.get("data", "")
        cb_id = callback.get("id", "")
        answer_callback(cb_id)
        if cb_chat_id == TELEGRAM_CHAT_ID and cb_data.startswith("cl:"):
            item_id = cb_data[3:]
            try:
                result = asyncio.run(handle_checklist_toggle(item_id))
            except Exception as e:
                result = {"text": f"Errore: {str(e)}"}
            edit_telegram_message(cb_message_id, result["text"], result.get("markup"))
        return jsonify({"ok": True})

    # Gestione messaggio normale
    message = data.get("message", {})
    chat_id = str(message.get("chat", {}).get("id", ""))
    text = message.get("text", "").strip()

    # Vocale / video nota → trascrizione Whisper
    voice = message.get("voice") or message.get("audio") or message.get("video_note")
    if not text and voice and chat_id == TELEGRAM_CHAT_ID:
        is_video = "video_note" in message
        transcribed = transcribe_voice(voice.get("file_id", ""), "video.mp4" if is_video else "voice.ogg")
        if transcribed:
            send_telegram(f"🎤 _{transcribed}_")
            text = transcribed
        else:
            send_telegram("Non sono riuscito a trascrivere il messaggio.")

    if text and chat_id == TELEGRAM_CHAT_ID:
        try:
            reply = asyncio.run(route_message(text))
        except Exception as e:
            import traceback as tb
            log_error(str(e), text, tb.format_exc())
            reply = f"⚠️ Errore interno. Ho loggato il problema."
        if isinstance(reply, dict):
            send_telegram(reply["text"], reply.get("markup"))
        else:
            send_telegram(reply)

    return jsonify({"ok": True})


@app.route("/api/tick")
def tick():
    _require_cron_secret()
    """Job unico ogni 5 min — gestisce morning, evening e reminders."""
    now = datetime.now(ROME)
    h, m = now.hour, now.minute
    done = []

    def _once(key: str) -> bool:
        """True se questa azione (key) non è ancora stata eseguita oggi — deduplica retry di cron-job.org."""
        if asyncio.run(already_ticked(key)):
            return False
        asyncio.run(mark_ticked(key))
        return True

    # Blocco unico 09:00: streak + nuovo mese + reminder abbonamenti/BNPL/prestiti +
    # scadenza Enable Banking + briefing mattutino — un solo messaggio Telegram
    if h == 9 and m <= 4 and _once(f"morning9:{now.date()}"):
        briefing = asyncio.run(get_morning_briefing())
        parts = [briefing]

        if now.day == 1:
            mese = mese_anno_it(now)
            parts.append(f"🗓️ *Nuovo mese!* Benvenuto in {mese} — budget resettato a zero. Buona fortuna! 💪")

        reminder_lines = []

        sub_msgs = asyncio.run(check_subscription_reminders())
        reminder_lines.extend(sub_msgs)
        if sub_msgs:
            done.append(f"sub_reminders:{len(sub_msgs)}")

        bnpl_msgs = asyncio.run(check_commitment_reminders())
        reminder_lines.extend(bnpl_msgs)
        if bnpl_msgs:
            done.append(f"bnpl_reminders:{len(bnpl_msgs)}")

        loan_msgs = asyncio.run(check_loan_reminders())
        reminder_lines.extend(loan_msgs)
        if loan_msgs:
            done.append(f"loan_reminders:{len(loan_msgs)}")

        days_left = session_expiry_days()
        if 0 <= days_left <= 5:
            reminder_lines.append(
                f"⚠️ *Enable Banking* scade tra {days_left} giorni ({days_left + 1}/09).\n"
                f"Rinnova l'autorizzazione Isybank per non perdere il sync automatico."
            )
            done.append("eb_expiry_reminder")

        if reminder_lines:
            parts.append("🔔 *PROMEMORIA*\n\n" + "\n\n".join(reminder_lines))

        days = asyncio.run(get_streak_days())
        parts.append("🎯 *STREAK*\n\n" + format_streak_message(days))

        send_telegram("\n\n━━━━━━━━━━━━━━━\n\n".join(parts))
        done.append("morning9")

    # Incoraggiamento streak dipendenza: 14:00 / 21:00 (09:00 incluso nel blocco sopra)
    if (h in (14, 21)) and m <= 4 and _once(f"streak:{now.date()}:{h}"):
        days = asyncio.run(get_streak_days())
        send_telegram(format_streak_message(days))
        done.append(f"streak:{days}")

    # Budget serale: 20:00 esatto
    if h == 20 and m <= 4 and _once(f"evening:{now.date()}"):
        alerts = asyncio.run(get_budget_alerts())
        if alerts:
            send_telegram(format_alerts(alerts))
        done.append("evening")

    # Riepilogo settimanale: domenica 20:00
    if now.weekday() == 6 and h == 20 and m <= 4 and _once(f"weekly:{now.date()}"):
        weekly = asyncio.run(get_weekly_spending())
        msg = format_weekly_summary(weekly)
        digest = asyncio.run(get_food_digest(days_back=7))
        msg += format_food_digest(digest)
        send_telegram(msg)
        done.append("weekly")

        anomalies = asyncio.run(get_spending_anomalies())
        if anomalies:
            send_telegram("📊 *Spese anomale questo mese*\n\n" + "\n".join(anomalies))
            done.append(f"anomalies:{len(anomalies)}")

    # Riepilogo mensile: ultimo giorno del mese alle 20:00
    import calendar as cal_mod
    last_day = cal_mod.monthrange(now.year, now.month)[1]
    if now.day == last_day and h == 20 and m <= 4 and _once(f"monthly:{now.date()}"):
        monthly = asyncio.run(get_monthly_spending())
        alerts = asyncio.run(get_budget_alerts())
        msg = f"📅 *Riepilogo {mese_anno_it(now)}*\n\n" + format_spending_summary(monthly)
        if alerts:
            msg += "\n\n" + format_alerts(alerts)
        send_telegram(msg)
        send_telegram("📊 Fine mese: quanto hai su Fineco (patrimonio ETF)? Rispondimi con l'importo per calcolare il patrimonio totale.")
        asyncio.run(save_pending("fineco_balance", {}))
        done.append("monthly")

    # Sync banca Enable Banking: 2x/giorno (08:00, 20:00) — ridotto da ogni 2h per stare
    # sotto la quota giornaliera ASPSP (rate limit scoperto il 03/07)
    if h in (8, 20) and m <= 4:
        result = asyncio.run(sync_transactions(days_back=3))
        done.append(f"bank_sync:{result.get('saved', 0)}saved")

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

    for ev in events:
        start = ev["start"]
        title = ev["title"]
        minutes_until = (start - now).total_seconds() / 60

        tomorrow = (now + timedelta(days=1)).date()
        # Giorno prima: 20:00-20:04
        if start.date() == tomorrow and h == 20 and m <= 4 and asyncio.run(already_ticked(f"day_before:{title}:{now.date()}")) is False:
            asyncio.run(mark_ticked(f"day_before:{title}:{now.date()}"))
            send_telegram(f"📅 Domani alle *{start.strftime('%H:%M')}*: *{title}*")
            sent.append(f"day_before:{title}")

        # 2 ore prima: finestra 10 min (115-124), copre eventuali salti del cron
        elif 115 <= minutes_until <= 124 and asyncio.run(already_ticked(f"2h:{title}:{start.isoformat()}")) is False:
            asyncio.run(mark_ticked(f"2h:{title}:{start.isoformat()}"))
            send_telegram(f"⏰ Tra 2 ore: *{title}* alle {start.strftime('%H:%M')}")
            sent.append(f"2h:{title}")

        # 1 ora prima: finestra 10 min (55-64)
        elif 55 <= minutes_until <= 64 and asyncio.run(already_ticked(f"1h:{title}:{start.isoformat()}")) is False:
            asyncio.run(mark_ticked(f"1h:{title}:{start.isoformat()}"))
            send_telegram(f"⏰ Tra 1 ora: *{title}* alle {start.strftime('%H:%M')}")
            sent.append(f"1h:{title}")

    return sent
