import logging
import asyncio
import aiosqlite
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
from telegram.constants import ParseMode
from telegram.error import Forbidden
from jikanpy import AioJikan
import random

# ================= CONFIGURATION =================
TOKEN = 'YOUR_BOT_TOKEN_HERE'  # Get from @BotFather
ADMIN_ID = 123456789           # Get from @userinfobot
CHANNEL_USERNAME = "@YourChannelName" # Your public channel
CHANNEL_LINK = "https://t.me/YourChannelLink" # Link to your channel
DB_NAME = "bot_database.db"

# ================= LOGGING SETUP =================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ================= DATABASE MANAGER =================
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        # Table for Users (Private Chats)
        await db.execute('''CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            status TEXT DEFAULT 'active'
        )''')
        # Table for Groups/Channels
        await db.execute('''CREATE TABLE IF NOT EXISTS chats (
            chat_id INTEGER PRIMARY KEY,
            chat_type TEXT
        )''')
        # Table for Anime Links Mapping (Anime Name -> Your Channel Link)
        await db.execute('''CREATE TABLE IF NOT EXISTS anime_links (
            anime_name TEXT PRIMARY KEY,
            post_link TEXT
        )''')
        await db.commit()

async def add_user(user_id):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id, status) VALUES (?, 'active')", (user_id,))
        await db.execute("UPDATE users SET status='active' WHERE user_id=?", (user_id,))
        await db.commit()

async def add_group(chat_id, chat_type):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR IGNORE INTO chats (chat_id, chat_type) VALUES (?, ?)", (chat_id, chat_type))
        await db.commit()

async def get_all_targets():
    """Fetch all users and groups."""
    async with aiosqlite.connect(DB_NAME) as db:
        users = await db.execute_fetchall("SELECT user_id FROM users WHERE status='active'")
        groups = await db.execute_fetchall("SELECT chat_id FROM chats")
        # Flatten list
        return [row[0] for row in users] + [row[0] for row in groups]

async def update_user_status(user_id, status):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE users SET status=? WHERE user_id=?", (status, user_id))
        await db.commit()

async def get_stats():
    async with aiosqlite.connect(DB_NAME) as db:
        active = await db.execute_fetchall("SELECT COUNT(*) FROM users WHERE status='active'")
        inactive = await db.execute_fetchall("SELECT COUNT(*) FROM users WHERE status='inactive'")
        groups = await db.execute_fetchall("SELECT COUNT(*) FROM chats")
        return active[0][0], inactive[0][0], groups[0][0]

# ================= CORE COMMANDS =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type == 'private':
        await add_user(chat.id)
        await update.message.reply_text(f"✅ Welcome! You will now receive AI recommendations and updates.")
    else:
        await add_group(chat.id, chat.type)
        await update.message.reply_text(f"✅ Bot activated in {chat.type} mode.")

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    
    active, inactive, groups = await get_stats()
    text = (
        f"📊 **ADMIN DASHBOARD** 📊\n\n"
        f"✅ Active Users: {active}\n"
        f"❌ Blocked Users: {inactive}\n"
        f"👥 Groups/Channels: {groups}\n\n"
        f"**Commands:**\n"
        f"/broadcast (reply to message)\n"
        f"/schedule <min> (reply to message)\n"
        f"/setlink <anime_name> | <link>"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

# ================= BROADCAST SYSTEM =================

async def send_to_one(context, chat_id, from_chat_id, message_id):
    """Helper to copy a message to a target."""
    try:
        await context.bot.copy_message(chat_id=chat_id, from_chat_id=from_chat_id, message_id=message_id)
        return True
    except Forbidden:
        # User blocked the bot
        await update_user_status(chat_id, 'inactive')
        return False
    except Exception as e:
        logger.error(f"Error sending to {chat_id}: {e}")
        return False

async def broadcast_logic(context, from_chat_id, message_id):
    targets = await get_all_targets()
    success_count = 0
    
    for chat_id in targets:
        if await send_to_one(context, chat_id, from_chat_id, message_id):
            success_count += 1
        await asyncio.sleep(0.05) # Flood limit protection
    
    return success_count

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    reply = update.message.reply_to_message
    if not reply:
        await update.message.reply_text("⚠️ Reply to a message (text/video/photo) to broadcast.")
        return

    msg = await update.message.reply_text("⏳ Broadcasting started...")
    count = await broadcast_logic(context, update.effective_chat.id, reply.message_id)
    await msg.edit_text(f"✅ Broadcast complete.\nReached: {count} users/groups.")

# ================= SCHEDULING SYSTEM =================

async def scheduled_job(context: ContextTypes.DEFAULT_TYPE):
    job_data = context.job.data
    admin_chat_id = job_data['admin_chat']
    message_id = job_data['msg_id']
    
    await broadcast_logic(context, admin_chat_id, message_id)
    await context.bot.send_message(admin_chat_id, "⏰ Scheduled Broadcast executed successfully!")

async def schedule_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Usage: /schedule 60 (Replies to a message to schedule it in 60 mins)"""
    if update.effective_user.id != ADMIN_ID: return
    reply = update.message.reply_to_message
    if not reply:
        await update.message.reply_text("⚠️ Reply to the message you want to schedule.")
        return
    
    try:
        minutes = int(context.args[0])
        context.job_queue.run_once(
            scheduled_job, 
            when=minutes * 60,
            data={'admin_chat': update.effective_chat.id, 'msg_id': reply.message_id}
        )
        await update.message.reply_text(f"✅ Message scheduled to broadcast in {minutes} minutes.")
    except (IndexError, ValueError):
        await update.message.reply_text("❌ Usage: /schedule <minutes>")

# ================= ANIME AI SYSTEM =================

async def set_anime_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Usage: /setlink Naruto | https://t.me/channel/123"""
    if update.effective_user.id != ADMIN_ID: return
    try:
        raw = ' '.join(context.args)
        anime_name, link = raw.split('|')
        anime_name = anime_name.strip().lower()
        link = link.strip()
        
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("INSERT OR REPLACE INTO anime_links VALUES (?, ?)", (anime_name, link))
            await db.commit()
        await update.message.reply_text(f"✅ Saved link for: {anime_name}")
    except ValueError:
        await update.message.reply_text("❌ Usage: /setlink Name | Link")

async def get_my_channel_link(anime_title):
    """Check database if we have a custom link for this anime."""
    async with aiosqlite.connect(DB_NAME) as db:
        # Simple fuzzy search
        cursor = await db.execute("SELECT post_link FROM anime_links WHERE ? LIKE '%' || anime_name || '%'", (anime_title.lower(),))
        row = await cursor.fetchone()
        return row[0] if row else None

async def anime_blog_job(context: ContextTypes.DEFAULT_TYPE):
    """Runs every 10 minutes to post MyAnimeList content."""
    jikan = AioJikan()
    try:
        # Fetch Top Anime (or Random)
        # Using "random" gives more variety but sometimes obscure stuff. 
        # Using "top" allows cycling through popular ones. Let's use Random for variety.
        try:
            response = await jikan.random(type='anime')
            anime = response['data']
        except:
            # Fallback if random fails/API limits
            await jikan.close()
            return

        title = anime.get('title', 'Unknown')
        score = anime.get('score', 'N/A')
        synopsis = anime.get('synopsis', 'No description.')
        if synopsis and len(synopsis) > 400: synopsis = synopsis[:400] + "..."
        img_url = anime['images']['jpg']['large_image_url']
        
        # Check internal DB for custom link
        custom_link = await get_my_channel_link(title)
        
        # Build Caption
        caption = f"🎬 <b>{title}</b>\n\n"
        caption += f"⭐ <b>Rating:</b> {score}/10\n"
        caption += f"📝 <b>Story:</b> {synopsis}\n\n"
        
        if custom_link:
            caption += f"📺 <b>Watch in our Channel:</b> <a href='{custom_link}'>{CHANNEL_USERNAME}</a>\n"
        else:
            caption += f"📺 <b>Where to watch:</b> Check Crunchyroll/Netflix\n"
            
        caption += f"\n----------------------------\n"
        caption += f"📣 <b>Ads sponsored by <a href='{CHANNEL_LINK}'>{CHANNEL_USERNAME}</a></b>\n"
        caption += f"<i>We do not do any copywrite thing but only gives recommendation to subscribers to watch it.</i>"
        
        # Broadcast to all
        targets = await get_all_targets()
        for chat_id in targets:
            try:
                await context.bot.send_photo(chat_id=chat_id, photo=img_url, caption=caption, parse_mode=ParseMode.HTML)
            except Exception:
                pass # Fail silently for auto-posts
                
    except Exception as e:
        logger.error(f"Anime Job Error: {e}")
    finally:
        await jikan.close()

# ================= MAIN LOOP =================

def main():
    # Initialize Application
    application = Application.builder().token(TOKEN).build()
    
    # Initialize DB
    loop = asyncio.get_event_loop()
    loop.run_until_complete(init_db())

    # Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin", admin_panel))
    application.add_handler(CommandHandler("broadcast", broadcast_command))
    application.add_handler(CommandHandler("schedule", schedule_command))
    application.add_handler(CommandHandler("setlink", set_anime_link))
    
    # Message Handler (Captures bot added to groups)
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, start))

    # Job Queue (The 10 minute automated poster)
    # 600 seconds = 10 minutes
    application.job_queue.run_repeating(anime_blog_job, interval=600, first=10)

    print("🤖 Bot is running 24/7...")
    application.run_polling()

if __name__ == "__main__":
    main()
