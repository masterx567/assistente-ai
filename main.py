import os
import asyncio
import logging
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv

load_dotenv()

from router import route_message
from scheduler_jobs import morning_briefing_job, budget_check_job

logging.basicConfig(level=logging.INFO)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    if chat_id != TELEGRAM_CHAT_ID:
        return
    text = update.message.text.strip()
    try:
        reply = await route_message(text)
        await update.message.reply_text(reply, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"⚠️ Errore: {str(e)}")


async def post_init(application: Application):
    scheduler = AsyncIOScheduler(timezone="Europe/Rome")
    scheduler.add_job(morning_briefing_job, "cron", hour=8, minute=0)
    scheduler.add_job(budget_check_job, "cron", hour=20, minute=0)
    scheduler.start()
    logging.info("Scheduler avviato")


def main():
    app = Application.builder().token(TELEGRAM_TOKEN).post_init(post_init).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logging.info("Bot avviato in polling mode")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
