import os
import asyncio
import json
from flask import Flask, request, jsonify
from dotenv import load_dotenv
import httpx

load_dotenv()

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from router import route_message
from agents.news import get_morning_briefing
from agents.budget import get_budget_alerts, format_alerts

app = Flask(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def send_telegram(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    with httpx.Client(timeout=9) as c:
        c.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"})


@app.route("/")
def root():
    return jsonify({"status": "ok"})


@app.route("/api/webhook", methods=["POST"])
def webhook():
    data = request.get_json(silent=True) or {}
    message = data.get("message", {})
    chat_id = str(message.get("chat", {}).get("id", ""))
    text = message.get("text", "").strip()

    if text and chat_id == TELEGRAM_CHAT_ID:
        reply = asyncio.run(route_message(text))
        send_telegram(reply)

    return jsonify({"ok": True})


@app.route("/api/morning")
def morning():
    briefing = asyncio.run(get_morning_briefing())
    send_telegram(briefing)
    return jsonify({"ok": True})


@app.route("/api/evening")
def evening():
    alerts = asyncio.run(get_budget_alerts())
    if alerts:
        send_telegram(format_alerts(alerts))
    return jsonify({"ok": True})
