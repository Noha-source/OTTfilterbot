import logging
import sqlite3
import asyncio
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
BOT_TOKEN = OS.GENTENV("BOT_TOKEN)
ADMIN_ID = 123456789  # Replace with your numeric Telegram ID
CHANNEL_ID = "@your_channel_username"  # Channel to sync ads/posts to

# --- LOGGING SETUP ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- DATABASE HANDLER ---
class Database:
    def __init__(self, db_name="bot_users.db"):
        self.conn = sqlite3.connect(db_name)
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

db = Database()

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
    # Feature 9: Client contact info
    await update.message.reply_text(
        "📢 **Promotion Inquiry**\n\n"
        "To promote your Channel, Group, or Website, please contact the admin:\n"
        f"👤 [Admin](tg://user?id={ADMIN_ID})",
        parse_mode=ParseMode.MARKDOWN
    )

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Feature 5: Show active user count
    if update.effective_user.id != ADMIN_ID:
        return
    
    count = db.count_users()
    await update.message.reply_text(f"📊 **Current Subscribers:** {count}")

# --- BROADCASTING ENGINE ---

async def broadcast_message(app, chat_id, message, sponsor_text=None):
    """Helper to copy message to a specific chat with optional sponsor text."""
    try:
        caption = (message.caption or "") 
        text = (message.text or "")
        
        # Append sponsor credit (Feature 2)
        if sponsor_text:
            credit = f"\n\n📢 **Sponsored By:** {sponsor_text}"
            if message.caption:
                caption += credit
            else:
                text += credit

        # Send based on message type
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
        # Feature 6 & 7: Auto-remove inactive users
        db.remove_user(chat_id)
        return False
    except BadRequest as e:
        logger.error(f"Bad Request for {chat_id}: {e}")
        return False
    except Exception as e:
        logger.error(f"Error sending to {chat_id}: {e}")
        return False

async def advertise(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Feature 1, 2, 3, 8, 10: Ad broadcasting
    if update.effective_user.id != ADMIN_ID:
        return

    # Syntax check: Admin must reply to a message and provide sponsor name
    if not update.message.reply_to_message:
        await update.message.reply_text("⚠️ Reply to the post you want to advertise.\nUsage: `/ad <SponsorName/Link>`")
        return

    sponsor = " ".join(context.args) if context.args else "Admin"
    post_to_promote = update.message.reply_to_message
    
    # 1. Post to Channel first (Feature 10)
    try:
        await broadcast_message(context.application, CHANNEL_ID, post_to_promote, sponsor)
        await update.message.reply_text(f"✅ Posted to {CHANNEL_ID}")
    except Exception as e:
        await update.message.reply_text(f"⚠️ Failed to post to channel: {e}")

    # 2. Broadcast to all bot subscribers
    users = db.get_users()
    sent_count = 0
    await update.message.reply_text(f"🚀 Starting broadcast to {len(users)} subscribers...")

    for user_id in users:
        success = await broadcast_message(context.application, user_id, post_to_promote, sponsor)
        if success:
            sent_count += 1
        await asyncio.sleep(0.05) # Throttle to avoid flooding

    await update.message.reply_text(f"✅ Broadcast complete. Reached {sent_count} active users.")

# --- AUTOMATED CONTENT (Feature 4) ---

async def auto_post_job(context: ContextTypes.DEFAULT_TYPE):
    """
    Feature 4: Automatically posts content.
    Replace the dummy text below with your scraping logic or API call.
    """
    # Placeholder content - You would insert your fetching logic here
    blog_content = (
        "🎬 **Entertainment Update**\n\n"
        "Here are the latest trending updates!\n"
        "1. Example Movie Review\n"
        "2. New Series Alert\n\n"
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
    # Feature 4: Admin controls time interval
    if update.effective_user.id != ADMIN_ID:
        return

    try:
        minutes = float(context.args[0])
        interval = minutes * 60
        
        job_queue = context.job_queue
        # Remove existing jobs
        current_jobs = job_queue.get_jobs_by_name("auto_post")
        for job in current_jobs:
            job.schedule_removal()
        
        # Add new job
        job_queue.run_repeating(auto_post_job, interval=interval, first=10, name="auto_post")
        await update.message.reply_text(f"⏰ Auto-post timer set to every {minutes} minutes.")
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: `/set_timer <minutes>`")

# --- MAIN ---

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Admin Handlers
    app.add_handler(CommandHandler("ad", advertise))      # Broadcasting
    app.add_handler(CommandHandler("stats", stats))       # Subscriber count
    app.add_handler(CommandHandler("set_timer", set_timer)) # Control frequency

    # User Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("contact", contact))

    # Initialize generic auto-post (default 15 mins)
    app.job_queue.run_repeating(auto_post_job, interval=900, first=60, name="auto_post")

    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
