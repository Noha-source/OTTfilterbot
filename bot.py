import logging
import sqlite3
import asyncio
import os
import sys
import threading
import random
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.constants import ParseMode
from telegram.error import Forbidden, BadRequest, InvalidToken
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    filters,
    Defaults
)

# --- CONFIGURATION ---
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
SPONSOR_CHANNEL = os.getenv("SPONSOR_CHANNEL", "@SponsorChannel")
PORT = int(os.getenv("PORT", 8080))
WITHDRAW_MIN = 200
EARN_PER_POST = 10

# Pre-flight check to prevent the loop errors seen in logs
if not TOKEN or ":" not in TOKEN:
    print("❌ FATAL ERROR: Invalid or missing BOT_TOKEN in Environment Variables.")
    sys.exit(1)

# --- LOGGING SETUP ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- DATABASE HANDLER ---
class Database:
    def __init__(self, db_name="bot_data.db"):
        self.conn = sqlite3.connect(db_name, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.create_tables()

    def create_tables(self):
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                join_date TEXT,
                status TEXT,
                balance INTEGER DEFAULT 0,
                warn_count INTEGER DEFAULT 0
            )
        """)
        self.conn.commit()

    def add_user(self, user_id, username):
        date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.cursor.execute(
            "INSERT OR IGNORE INTO users (user_id, username, join_date, status) VALUES (?, ?, ?, ?)",
            (user_id, username, date, "active")
        )
        self.conn.commit()

    def update_balance(self, user_id, amount):
        self.cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
        self.conn.commit()

db = Database()

# --- AI XMDB BLOG GENERATOR ---
def generate_ai_content():
    movies = ["Pushpa 2", "Kalki 2898 AD", "Deadpool & Wolverine", "Squid Game S2", "Heeramandi"]
    platforms = ["Netflix", "Prime Video", "JioCinema", "Disney+ Hotstar"]
    movie = random.choice(movies)
    platform = random.choice(platforms)
    
    blog = (
        f"🎬 **XMDB AI UPDATE: {movie}**\n\n"
        f"This trending hit is currently dominating {platform}! "
        "Experience the best of Bollywood and Hollywood storytelling.\n\n"
        f"🌟 **Rating:** ⭐⭐⭐⭐⭐\n"
        f"🔗 **Watch on:** {platform}\n\n"
        f"📢 **Sponsor:** {SPONSOR_CHANNEL}\n"
        f"✅ *Join our sponsor for premium access!*"
    )
    return blog

# --- AUTOMATED TASKS ---
async def auto_post_job(context: ContextTypes.DEFAULT_TYPE):
    content = generate_ai_content()
    # Fetch all active users
    db.cursor.execute("SELECT user_id FROM users WHERE status = 'active'")
    users = db.cursor.fetchall()
    
    success_count = 0
    for (u_id,) in users:
        try:
            await context.bot.send_message(chat_id=u_id, text=content, parse_mode=ParseMode.MARKDOWN)
            success_count += 1
        except Forbidden:
            db.cursor.execute("UPDATE users SET status = 'inactive' WHERE user_id = ?", (u_id,))
            db.conn.commit()
        except Exception:
            pass
    
    # Earn 10rs per automatic post
    db.update_balance(ADMIN_ID, EARN_PER_POST)
    logger.info(f"Auto-post complete. Reached {success_count} users. Admin earned ₹{EARN_PER_POST}.")

# --- COMMAND HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.add_user(user.id, user.username)
    
    welcome_text = (
        f"👋 **Welcome, {user.first_name}!**\n\n"
        "You are now subscribed to **XMDB AI Movie Updates**.\n"
        "🚀 You will receive Bollywood & Hollywood reviews every 5 minutes!\n\n"
        f"📢 **Join Sponsor:** {SPONSOR_CHANNEL}\n"
        "⚠️ *Spammers will be warned and banned.*"
    )
    await update.message.reply_text(welcome_text, parse_mode=ParseMode.MARKDOWN)

async def withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    
    db.cursor.execute("SELECT balance FROM users WHERE user_id = ?", (ADMIN_ID,))
    balance = db.cursor.fetchone()[0]
    
    if balance >= WITHDRAW_MIN:
        await update.message.reply_text(f"💰 **Balance:** ₹{balance}\nProcessing withdrawal to UPI/Bank... ✅")
        db.cursor.execute("UPDATE users SET balance = 0 WHERE user_id = ?", (ADMIN_ID,))
        db.conn.commit()
    else:
        await update.message.reply_text(f"❌ Minimum ₹{WITHDRAW_MIN} required. Current: ₹{balance}")

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin tool to post ads/personal messages manually."""
    if update.effective_user.id != ADMIN_ID:
        return
    
    if not update.message.reply_to_message:
        await update.message.reply_text("⚠️ Reply to a message to broadcast it.")
        return

    db.cursor.execute("SELECT user_id FROM users WHERE status = 'active'")
    users = db.cursor.fetchall()
    
    for (u_id,) in users:
        try:
            await context.bot.copy_message(chat_id=u_id, from_chat_id=update.message.chat_id, 
                                          message_id=update.message.reply_to_message.message_id)
        except Exception:
            pass
    await update.message.reply_text("✅ Broadcast complete.")

# --- WEB SERVER (For Render Health Check) ---
class HealthCheck(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers()
        self.wfile.write(b"AI Movie Bot is Active")

def run_server():
    HTTPServer(("0.0.0.0", PORT), HealthCheck).serve_forever()

# --- MAIN ---
def main():
    threading.Thread(target=run_server, daemon=True).start()
    
    try:
        app = ApplicationBuilder().token(TOKEN).build()
        
        # Handlers
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("withdraw", withdraw))
        app.add_handler(CommandHandler("ad", broadcast))
        app.add_handler(CommandHandler("broadcast", broadcast))
        
        # Scheduler: 5 Minutes (300 seconds)
        app.job_queue.run_repeating(auto_post_job, interval=300, first=10)
        
        print("🤖 Bot is starting polling...")
        app.run_polling()
    except InvalidToken:
        logger.error("❌ TOKEN REJECTED. Please check your Render Environment Variables.")

if __name__ == "__main__":
    main()
