import logging
import sqlite3
import asyncio
import os
import sys
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.constants import ParseMode
from telegram.error import Forbidden, BadRequest, InvalidToken
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
)

# --- CONFIGURATION ---
# Fetches values from Render's Environment Variables
TOKEN = os.getenv("BOT_TOKEN")

# Fix for "InvalidToken" error: stop execution if token is obviously fake
if not TOKEN or TOKEN == "YOUR_BOT_TOKEN_HERE" or ":" not in TOKEN:
    print("❌ CRITICAL ERROR: 'BOT_TOKEN' is missing or invalid in Environment Variables.")
    sys.exit(1)

# Fetches ADMIN_ID from Env; defaults to 0 if not set
try:
    ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
except ValueError:
    ADMIN_ID = 0

CHANNEL_ID = os.getenv("CHANNEL_ID", "@your_channel_username")

# --- LOGGING SETUP ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- HEALTH CHECK SERVER (For Render) ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is online")
    def log_message(self, format, *args):
        return

def start_web_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    logger.info(f"✅ Health server active on port {port}")
    server.serve_forever()

# --- DATABASE HANDLER ---
class Database:
    def __init__(self, db_name="bot_users.db"):
        self.conn = sqlite3.connect(db_name, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.create_table()

    def create_table(self):
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT
            )
        """)
        self.conn.commit()

    def add_user(self, user_id, username):
        self.cursor.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (user_id, username))
        self.conn.commit()

    def get_users(self):
        self.cursor.execute("SELECT user_id FROM users")
        return [row[0] for row in self.cursor.fetchall()]

    def count_users(self):
        self.cursor.execute("SELECT COUNT(*) FROM users")
        return self.cursor.fetchone()[0]

db = Database()

# --- COMMAND HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.add_user(user.id, user.username)
    await update.message.reply_text(f"👋 Welcome {user.first_name}! Use /contact for admin info.")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    count = db.count_users()
    await update.message.reply_text(f"📊 Total Subscribers: {count}")

async def advertise(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ Reply to a post to broadcast it.")
        return

    users = db.get_users()
    sent = 0
    for u_id in users:
        try:
            await context.bot.copy_message(chat_id=u_id, from_chat_id=update.message.chat_id, message_id=update.message.reply_to_message.message_id)
            sent += 1
            await asyncio.sleep(0.05)
        except Exception:
            pass
    await update.message.reply_text(f"✅ Broadcast complete. Reached {sent} users.")

# --- MAIN ---
def main():
    threading.Thread(target=start_web_server, daemon=True).start()

    try:
        app = ApplicationBuilder().token(TOKEN).build()
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("stats", stats))
        app.add_handler(CommandHandler("ad", advertise))

        logger.info("🤖 Bot is starting...")
        app.run_polling()
    except InvalidToken:
        logger.error("❌ The provided BOT_TOKEN was rejected by Telegram.")
    except Exception as e:
        logger.error(f"❌ Crash error: {e}")

if __name__ == "__main__":
    main()
