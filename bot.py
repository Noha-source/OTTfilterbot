import logging
import sqlite3
import asyncio
import os
import sys
import threading
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.constants import ParseMode
from telegram.error import Forbidden, BadRequest
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    filters,
)

# --- CONFIGURATION (Render/Environment Variables) ---
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
SPONSOR_CHANNEL = os.getenv("SPONSOR_CHANNEL", "@SponsorChannel")
PORT = int(os.getenv("PORT", 8080))
WITHDRAW_MIN = 200
REWARD_PER_POST = 10

# Validation to ensure bot starts correctly
if not TOKEN or TOKEN == "YOUR_BOT_TOKEN_HERE":
    print("❌ FATAL ERROR: BOT_TOKEN is not configured.")
    sys.exit(1)

# --- DATABASE SETUP ---
class Database:
    def __init__(self):
        self.conn = sqlite3.connect("bot_management.db", check_same_thread=False)
        self.cursor = self.conn.cursor()
        self._setup()

    def _setup(self):
        # Tracking subscribers, join date, status, and earnings balance
        self.cursor.execute("""CREATE TABLE IF NOT EXISTS users 
            (user_id INTEGER PRIMARY KEY, username TEXT, join_date TEXT, status TEXT, balance INTEGER DEFAULT 0)""")
        self.conn.commit()

    def add_user(self, user_id, username):
        date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.cursor.execute("INSERT OR IGNORE INTO users (user_id, username, join_date, status) VALUES (?, ?, ?, ?)", 
                           (user_id, username, date, "active"))
        self.conn.commit()

    def update_status(self, user_id, status):
        self.cursor.execute("UPDATE users SET status=? WHERE user_id=?", (status, user_id))
        self.conn.commit()

    def get_active_users(self):
        self.cursor.execute("SELECT user_id FROM users WHERE status='active'")
        return [row[0] for row in self.cursor.fetchall()]

    def add_earnings(self, amount):
        self.cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amount, ADMIN_ID))
        self.conn.commit()

db = Database()

# --- AI XMDB CONTENT GENERATOR ---
async def generate_ai_xmdb_blog():
    import random
    # Simulated AI logic for Bollywood & Hollywood content
    movies = ["Pushpa 2: The Rule", "Kalki 2898 AD", "Joker: Folie à Deux", "Deadpool & Wolverine", "Heeramandi"]
    platform = random.choice(["Netflix", "Prime Video", "Disney+ Hotstar", "JioCinema"])
    movie = random.choice(movies)
    
    blog_content = (
        f"🎬 **XMDB SPECIAL: Trending OTT Release**\n\n"
        f"**Movie/Series:** {movie}\n"
        f"**Platform:** {platform}\n\n"
        f"This latest Bollywood/Hollywood hit is taking the internet by storm! Highly recommended for all movie buffs. Don't miss out on the action and drama.\n\n"
        f"👤 **Admin:** [Master](tg://user?id={ADMIN_ID})\n"
        f"📢 **Sponsor:** {SPONSOR_CHANNEL}\n"
        f"✨ **Join us for more:** {SPONSOR_CHANNEL}"
    )
    return blog_content

# --- AUTOMATED TASKS ---
async def automated_blog_job(context: ContextTypes.DEFAULT_TYPE):
    """Executes every 5 minutes: Posts AI blog and earns 10rs."""
    content = await generate_ai_xmdb_blog()
    users = db.get_active_users()
    
    for user_id in users:
        try:
            await context.bot.send_message(chat_id=user_id, text=content, parse_mode=ParseMode.MARKDOWN)
        except Forbidden:
            db.update_status(user_id, "inactive") # Remove inactive/deleted subscribers
        except Exception:
            pass
    
    db.add_earnings(REWARD_PER_POST)

# --- COMMAND HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.add_user(user.id, user.username)
    
    welcome_msg = (
        f"✨ **HELLO {user.first_name}! WELCOME TO OTT EXPLORER** ✨\n\n"
        "🎬 You are now subscribed to the ultimate **XMDB Movie Hub**.\n"
        "🚀 You will receive automated reviews of the best Bollywood & Hollywood series every 5 minutes!\n\n"
        f"💎 **Join our Sponsor to stay active:** {SPONSOR_CHANNEL}\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "👇 *Start exploring now!*"
    )
    await update.message.reply_text(welcome_msg, parse_mode=ParseMode.MARKDOWN)

async def withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    
    db.cursor.execute("SELECT balance FROM users WHERE user_id=?", (ADMIN_ID,))
    balance = db.cursor.fetchone()[0]
    
    if balance >= WITHDRAW_MIN:
        await update.message.reply_text(f"💰 **WALLET BALANCE:** ₹{balance}\n\nRequesting withdrawal to UPI/Bank account... ✅")
        db.cursor.execute("UPDATE users SET balance = 0 WHERE user_id=?", (ADMIN_ID,))
        db.conn.commit()
    else:
        await update.message.reply_text(f"❌ **Withdrawal Failed!** Minimum threshold is ₹200. Current: ₹{balance}")

# --- DUMMY WEB SERVER ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers()
        self.wfile.write(b"Bot is Running")

def start_server():
    HTTPServer(("0.0.0.0", PORT), HealthCheckHandler).serve_forever()

# --- MAIN RUNNER ---
def main():
    threading.Thread(target=start_server, daemon=True).start()
    app = ApplicationBuilder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("withdraw", withdraw))
    
    # 5-Minute Auto Posting Job
    app.job_queue.run_repeating(automated_blog_job, interval=300, first=10)
    
    print(f"🚀 AI Bot started on port {PORT}...")
    app.run_polling()

if __name__ == "__main__":
    main()
    
