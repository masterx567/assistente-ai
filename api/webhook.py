import os
import json
import httpx
from http.server import BaseHTTPRequestHandler
from dotenv import load_dotenv

load_dotenv()

from router import route_message

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def send_telegram_sync(text: str, chat_id: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    with httpx.Client(timeout=8) as c:
        c.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"})


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            data = json.loads(body)
            message = data.get("message", {})
            chat_id = str(message.get("chat", {}).get("id", ""))
            text = message.get("text", "").strip()

            if text and chat_id == TELEGRAM_CHAT_ID:
                import asyncio
                reply = asyncio.run(route_message(text))
                send_telegram_sync(reply, chat_id)
        except Exception as e:
            pass

        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"status":"ok"}')
