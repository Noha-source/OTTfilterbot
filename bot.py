import logging
import sqlite3
import asyncio
import os
import sys
import threading
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

# --- CONFIGURATION ---
# We use a try/except block to catch configuration errors early
try:
    TOKEN = os.getenv("BOT_TOKEN")
    if not TOKEN:
        print("CRITICAL ERROR: 'BOT_TOKEN' environment variable is missing.")
        sys.exit(1)
        
    ADMIN_ID = 123456789  # <--- REPLACE with your actual Numeric ID
    CHANNEL_ID = "@your_channel_username"  # <--- REPLACE with your Channel Username
except Exception as e:
    print(f"Configuration Error: {e}")
    sys.exit(1)

# --- LOGGING SETUP ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- DUMMY WEB SERVER (FOR RENDER) ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running!")

    # Suppress log messages for the health check to keep logs clean
    def log_message(self, format, *args):
        return

def start_web_server():
    try:
        port = int(os.environ.get("PORT", 8080))
        server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
        logger.info(f"✅ Web server running on port {port}")
        server.serve_forever()
    except Exception as e:
        logger.error(f"❌ Web server failed to start: {e}")
        # If web server fails, we don't exit because the bot might still work,
        # but Render will likely kill it.

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
                username TEXT,
                joined_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.conn.commit()

    def add_user(self, user_id, username):
        try:
            self.cursor.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (user_id, username))
            self.conn.commit()
        except Exception as e:
            logger.error(f"DB Error: {e}")

    def get_users(self):
        self.cursor.execute("SELECT user_id FROM users")
        return [row[0] for row in self.cursor.fetchall()]

    def remove_user(self, user_id):
        self.cursor.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
        self.conn.commit()

    def count_users(self):
        self.cursor.execute("SELECT COUNT(*) FROM users")
        return self.cursor.fetchone()[0]

# Initialize DB
try:
    db = Database()
except Exception as e:
    logger.error(f"Failed to initialize database: {e}")
    sys.exit(1)

# --- COMMANDS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.add_user(user.id, user.username)
    await update.message.reply_text(
        f"👋 Welcome, {user.first_name}!\n\n"
        "You are now subscribed to updates. "
        "Contact admin for promotions: /contact"
    )

async def contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📢 **Promotion Inquiry**\n\n"
        "To promote your Channel, Group, or Website, please contact the admin:\n"
        f"👤 [Admin](tg://user?id={ADMIN_ID})",
        parse_mode=ParseMode.MARKDOWN
    )

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    count = db.count_users()
    await update.message.reply_text(f"📊 **Current Subscribers:** {count}")

# --- BROADCASTING ENGINE ---

async def broadcast_message(app, chat_id, message, sponsor_text=None):
    try:
        caption = (message.caption or "") 
        text = (message.text or "")
        
        if sponsor_text:
            credit = f"\n\n📢 **Sponsored By:** {sponsor_text}"
            if message.caption:
                caption += credit
            else:
                text += credit

        if message.text:
            await app.bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.MARKDOWN)
        else:
            await app.bot.copy_message(
                chat_id=chat_id,
                from_chat_id=message.chat_id,
                message_id=message.message_id,
                caption=caption,
                parse_mode=ParseMode.MARKDOWN
            )
        return True
    except Forbidden:
        db.remove_user(chat_id)
        return False
    except BadRequest as e:
        logger.error(f"Bad Request for {chat_id}: {e}")
        return False
    except Exception as e:
        logger.error(f"Error sending to {chat_id}: {e}")
        return False

async def advertise(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    if not update.message.reply_to_message:
        await update.message.reply_text("⚠️ Reply to the post you want to advertise.\nUsage: `/ad <SponsorName/Link>`")
        return

    sponsor = " ".join(context.args) if context.args else "Admin"
    post_to_promote = update.message.reply_to_message
    
    try:
        await broadcast_message(context.application, CHANNEL_ID, post_to_promote, sponsor)
        await update.message.reply_text(f"✅ Posted to {CHANNEL_ID}")
    except Exception as e:
        await update.message.reply_text(f"⚠️ Failed to post to channel: {e}")

    users = db.get_users()
    sent_count = 0
    await update.message.reply_text(f"🚀 Starting broadcast to {len(users)} subscribers...")

    for user_id in users:
        success = await broadcast_message(context.application, user_id, post_to_promote, sponsor)
        if success:
            sent_count += 1
        await asyncio.sleep(0.05) 

    await update.message.reply_text(f"✅ Broadcast complete. Reached {sent_count} active users.")

# --- AUTOMATED CONTENT ---

async def auto_post_job(context: ContextTypes.DEFAULT_TYPE):
    blog_content = (
        "🎬 **Entertainment Update**\n\n"
        "Here are the latest trending updates!\n"
        "🔗 [Read More](https://google.com)"
    )
    
    # Send to Channel
    try:
        await context.bot.send_message(chat_id=CHANNEL_ID, text=blog_content, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"Auto-post channel error: {e}")

    # Send to Subscribers
    users = db.get_users()
    for user_id in users:
        try:
            await context.bot.send_message(chat_id=user_id, text=blog_content, parse_mode=ParseMode.MARKDOWN)
        except Forbidden:
            db.remove_user(user_id)
        except Exception:
            pass

async def set_timer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    try:
        minutes = float(context.args[0])
        interval = minutes * 60
        job_queue = context.job_queue
        current_jobs = job_queue.get_jobs_by_name("auto_post")
        for job in current_jobs:
            job.schedule_removal()
        job_queue.run_repeating(auto_post_job, interval=interval, first=10, name="auto_post")
        await update.message.reply_text(f"⏰ Auto-post timer set to every {minutes} minutes.")
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: `/set_timer <minutes>`")

# --- MAIN ---

def main():
    print("--- STARTING BOT ---")
    
    # 1. Start the Dummy Web Server in a separate thread
    web_thread = threading.Thread(target=start_web_server, daemon=True)
    web_thread.start()

    # 2. Start the Telegram Bot
    try:
        app = ApplicationBuilder().token(TOKEN).build()
    except Exception as e:
        print(f"CRITICAL: Failed to build application. Token valid? {e}")
        sys.exit(1)

    app.add_handler(CommandHandler("ad", advertise))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("set_timer", set_timer))
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("contact", contact))

    app.job_queue.run_repeating(auto_post_job, interval=900, first=60, name="auto_post")

    print("✅ Bot is polling...")
    app.run_polling()

if __name__ == "__main__":
    main()
