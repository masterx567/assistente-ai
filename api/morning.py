import os
import asyncio
import httpx
from http.server import BaseHTTPRequestHandler
from dotenv import load_dotenv

load_dotenv()

from agents.news import get_morning_briefing

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def send_telegram_sync(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    with httpx.Client(timeout=8) as c:
        c.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"})


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            briefing = asyncio.run(get_morning_briefing())
            send_telegram_sync(briefing)
        except Exception as e:
            send_telegram_sync(f"⚠️ Errore briefing: {str(e)}")

        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def do_POST(self):
        self.do_GET()
