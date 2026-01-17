import logging
import sqlite3
import asyncio
import os
import sys
import threading
import requests
import random
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.constants import ParseMode
from telegram.error import Forbidden, BadRequest, InvalidToken
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters

# --- CONFIGURATION ---
TOKEN = os.getenv("BOT_TOKEN")
XMDB_API_KEY = os.getenv("XMDB_API_KEY")  # Get from http://www.omdbapi.com/
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
SPONSOR_CHANNEL = os.getenv("CHANNEL_ID", "@SponsorChannel")
PORT = int(os.environ.get("PORT", 8080))
EARNINGS_PER_POST = 10  # Amount earned per automated post (in ₹)

if not TOKEN or ":" not in TOKEN:
    print("❌ FATAL: BOT_TOKEN is missing or invalid.")
    sys.exit(1)

# --- DATABASE ---
class Database:
    def __init__(self):
        self.conn = sqlite3.connect("bot_data.db", check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.setup()

    def setup(self):
        # Tracking users and their individual join dates
        self.cursor.execute("""CREATE TABLE IF NOT EXISTS users 
            (user_id INTEGER PRIMARY KEY, username TEXT, join_date TEXT, earnings INTEGER DEFAULT 0)""")
        # Global earnings tracking for the admin
        self.cursor.execute("CREATE TABLE IF NOT EXISTS admin_stats (total_earned INTEGER DEFAULT 0)")
        self.cursor.execute("INSERT OR IGNORE INTO admin_stats (rowid, total_earned) VALUES (1, 0)")
        self.conn.commit()

    def add_user(self, user_id, username):
        date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.cursor.execute("INSERT OR IGNORE INTO users (user_id, username, join_date) VALUES (?, ?, ?)", (user_id, username, date))
        self.conn.commit()

    def increment_earnings(self, amount):
        self.cursor.execute("UPDATE admin_stats SET total_earned = total_earned + ? WHERE rowid = 1", (amount,))
        self.conn.commit()

db = Database()

# --- MOVIE API FETCH (XMDB/OMDb) ---
async def fetch_movie_data():
    """Fetches real movie details and posters using OMDb API."""
    trending = ["Pathaan", "Inception", "Interstellar", "Stree 2", "The Dark Knight", "Dune", "Pushpa"]
    movie_name = random.choice(trending)
    url = f"http://www.omdbapi.com/?apikey={XMDB_API_KEY}&t={movie_name}&plot=short"
    
    try:
        response = requests.get(url).json()
        if response.get("Response") == "True":
            return response
    except Exception as e:
        logging.error(f"XMDB API Error: {e}")
    return None

# --- AUTOMATED BLOG JOB ---
async def auto_post_job(context: ContextTypes.DEFAULT_TYPE):
    """Broadcasts a movie poster and blog every 5 minutes."""
    data = await fetch_movie_data()
    if not data: return

    # Format the Blog Post
    blog_text = (
        f"🎬 **XMDB SPECIAL: {data.get('Title')} ({data.get('Year')})**\n\n"
        f"📝 **Description:** {data.get('Plot')}\n\n"
        f"⭐ **Global Rating:** {data.get('imdbRating')}/10\n"
        f"🎭 **Genre:** {data.get('Genre')}\n\n"
        f"✅ **Why Watch?** This is a top-rated masterpiece trending across OTT platforms! Highly recommended for a weekend binge.\n\n"
        f"📢 **Join Sponsor:** {SPONSOR_CHANNEL}\n"
        f"👤 **Admin:** [Contact](tg://user?id={ADMIN_ID})"
    )

    db.cursor.execute("SELECT user_id FROM users")
    users = db.cursor.fetchall()
    
    for (user_id,) in users:
        try:
            # Send movie poster with the blog as caption
            await context.bot.send_photo(
                chat_id=user_id, 
                photo=data.get('Poster'), 
                caption=blog_text, 
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception: pass
    
    # Track earnings (Admin earns ₹10 per automated post)
    db.increment_earnings(EARNINGS_PER_POST)

# --- ADMIN COMMANDS ---
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    
    db.cursor.execute("SELECT COUNT(*) FROM users")
    user_count = db.cursor.fetchone()[0]
    db.cursor.execute("SELECT total_earned FROM admin_stats WHERE rowid = 1")
    total_earned = db.cursor.fetchone()[0]
    
    await update.message.reply_text(
        f"📊 **ADMIN DASHBOARD**\n\n"
        f"👥 **Total Subscribers:** {user_count}\n"
        f"💰 **Total Earned:** ₹{total_earned}\n"
        f"💸 **Earned per Post:** ₹{EARNINGS_PER_POST}\n\n"
        f"The bot posts every 5 minutes automatically."
    )

# --- CORE HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.add_user(user.id, user.username)
    await update.message.reply_text(
        f"✨ **Welcome {user.first_name} to OTT Hub!**\n\n"
        f"You will now receive automatic AI movie blogs and OTT recommendations every 5 minutes.\n\n"
        f"📢 **Recommended Sponsor:** {SPONSOR_CHANNEL}"
    )

# --- MAIN RUNNER ---
def main():
    # Start health server for Render
    threading.Thread(target=lambda: HTTPServer(("0.0.0.0", PORT), HealthHandler).serve_forever(), daemon=True).start()
    
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", stats))
    
    # 5-Minute Auto Posting Job (300 seconds)
    if app.job_queue:
        app.job_queue.run_repeating(auto_post_job, interval=300, first=10)
    
    print("🤖 AI Movie Bot is polling...")
    app.run_polling()

if __name__ == "__main__":
    main()
    
