import logging
import sqlite3
import requests
import asyncio
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# --- CONFIGURATION (Render Environment Variables) ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
TMDB_API_KEY = os.getenv("TMDB_API_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0")) 
DB_FILE = "bot_users.db"

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, is_banned BOOLEAN DEFAULT 0)')
    conn.commit()
    conn.close()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Welcome to the OTT Filter Bot!")

if __name__ == '__main__':
    init_db()
    if not BOT_TOKEN:
        print("CRITICAL ERROR: BOT_TOKEN not found.")
        exit(1)
        
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler('start', start))
    
    print("🤖 Bot is running...")
    application.run_polling()
    
