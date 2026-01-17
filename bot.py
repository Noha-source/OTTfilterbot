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

# --- PRE-FLIGHT CHECK & CONFIGURATION ---
TOKEN = os.getenv("BOT_TOKEN")
# Remove any accidental spaces or quotes from the token string
if TOKEN:
    TOKEN = TOKEN.strip().replace('"', '').replace("'", "")

ADMIN_ID_STR = os.getenv("ADMIN_ID")
CHANNEL_ID = os.getenv("CHANNEL_ID")

# Validation to prevent the "InvalidToken" loop
if not TOKEN or TOKEN == "YOUR_BOT_TOKEN_HERE" or ":" not in TOKEN:
    print("❌ FATAL ERROR: BOT_TOKEN is missing or invalid in Render Environment Variables.")
    sys.exit(1)

try:
    ADMIN_ID = int(ADMIN_ID_STR) if ADMIN_ID_STR else 0
except ValueError:
    print(f"⚠️ WARNING: ADMIN_ID '{ADMIN_ID_STR}' is not a number. Admin commands will fail.")
    ADMIN_ID = 0

# --- LOGGING SETUP ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- HEALTH CHECK SERVER (Mandatory for Render) ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is alive")
    def log_message(self, format, *args): return

def start_web_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    logger.info(f"✅ Health check server active on port {port}")
    server.serve_forever()

# --- DATABASE ---
class Database:
    def __init__(self, db_name="bot_users.db"):
        self.conn = sqlite3.connect(db_name, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.cursor.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY)")
        self.conn.commit()

    def add_user(self, user_id):
        self.cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
        self.conn.commit()

    def get_users(self):
        self.cursor.execute("SELECT user_id FROM users")
        return [row[0] for row in self.cursor.fetchall()]

db = Database()

# --- COMMANDS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db.add_user(update.effective_user.id)
    await update.message.reply_text("👋 Welcome! You are now subscribed to updates.")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    users = db.get_users()
    await update.message.reply_text(f"📊 Total Users: {len(users)}")

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ Reply to a message to broadcast it.")
        return

    users = db.get_users()
    sent = 0
    for u_id in users:
        try:
            await context.bot.copy_message(chat_id=u_id, from_chat_id=update.message.chat_id, 
                                          message_id=update.message.reply_to_message.message_id)
            sent += 1
            await asyncio.sleep(0.05)
        except Exception: pass
    await update.message.reply_text(f"✅ Sent to {sent} users.")

# --- MAIN ---
def main():
    threading.Thread(target=start_web_server, daemon=True).start()
    try:
        app = ApplicationBuilder().token(TOKEN).build()
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("stats", stats))
        app.add_handler(CommandHandler("ad", broadcast))
        app.add_handler(CommandHandler("broadcast", broadcast))

        logger.info("🤖 Bot starting polling...")
        app.run_polling()
    except InvalidToken:
        logger.error("❌ Invalid Token! Verify BOT_TOKEN in Render Environment Variables.")
    except Exception as e:
        logger.error(f"❌ Critical error: {e}")

if __name__ == "__main__":
    main()
