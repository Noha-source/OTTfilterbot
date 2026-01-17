Here is the updated script. I have **removed `jikanpy**` and replaced the `auto_blog_job` logic with **AniList GraphQL** queries.

I have kept the database, broadcasting system, web server, and all admin commands exactly as they were.

### `main.py`

```python
import logging
import asyncio
import os
import sys
import random  # Added for random page selection
from datetime import datetime, timedelta
from aiohttp import web, ClientSession  # Added ClientSession for GraphQL requests
import aiosqlite
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
from telegram.constants import ParseMode
from telegram.error import Forbidden
# Removed: from jikanpy import AioJikan

# ================= CONFIGURATION =================
# These are loaded from Render Environment Variables.
# If testing locally, replace the second value with your actual data.
TOKEN = os.getenv('TOKEN', 'YOUR_BOT_TOKEN_HERE') 
ADMIN_ID = int(os.getenv('ADMIN_ID', '123456789')) 
CHANNEL_NAME = os.getenv('CHANNEL_NAME', 'My Anime Channel')
CHANNEL_LINK = os.getenv('CHANNEL_LINK', 'https://t.me/your_channel_link')
PORT = int(os.getenv('PORT', 8080)) # Required for Render Web Services
DB_NAME = "bot_data.db"

# ================= LOGGING =================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ================= DATABASE MANAGER =================
async def init_db():
    """Initializes the database tables."""
    async with aiosqlite.connect(DB_NAME) as db:
        # Table: Users (Private Chats)
        await db.execute('''CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            status TEXT DEFAULT 'active',
            joined_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        # Table: Groups (Public Chats)
        await db.execute('''CREATE TABLE IF NOT EXISTS groups (
            chat_id INTEGER PRIMARY KEY,
            title TEXT
        )''')
        # Table: Anime Links (Maps Anime Names to Your Channel Posts)
        await db.execute('''CREATE TABLE IF NOT EXISTS anime_links (
            anime_name TEXT PRIMARY KEY,
            post_link TEXT
        )''')
        await db.commit()

async def register_user(user_id):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
        await db.execute("UPDATE users SET status='active' WHERE user_id=?", (user_id,))
        await db.commit()

async def register_group(chat_id, title):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR IGNORE INTO groups (chat_id, title) VALUES (?, ?)", (chat_id, title))
        await db.commit()

async def get_all_chats():
    """Returns a list of all active User IDs and Group IDs."""
    async with aiosqlite.connect(DB_NAME) as db:
        users = await db.execute_fetchall("SELECT user_id FROM users WHERE status='active'")
        groups = await db.execute_fetchall("SELECT chat_id FROM groups")
        return [row[0] for row in users] + [row[0] for row in groups]

async def mark_inactive(user_id):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE users SET status='inactive' WHERE user_id=?", (user_id,))
        await db.commit()

async def get_stats():
    async with aiosqlite.connect(DB_NAME) as db:
        active = await db.execute_fetchall("SELECT COUNT(*) FROM users WHERE status='active'")
        inactive = await db.execute_fetchall("SELECT COUNT(*) FROM users WHERE status='inactive'")
        groups = await db.execute_fetchall("SELECT COUNT(*) FROM groups")
        return active[0][0], inactive[0][0], groups[0][0]

async def get_custom_link(anime_title):
    """Checks if we have a specific channel link for this anime."""
    async with aiosqlite.connect(DB_NAME) as db:
        # Fuzzy search: checks if the saved name is inside the MAL title
        cursor = await db.execute("SELECT post_link FROM anime_links WHERE ? LIKE '%' || anime_name || '%'", (anime_title.lower(),))
        row = await cursor.fetchone()
        return row[0] if row else None

# ================= WEB SERVER (KEEP-ALIVE) =================
# This allows the bot to run on Render "Web Services" by binding to a port.
async def health_check(request):
    return web.Response(text="Bot is ALIVE and Running 24/7!")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    logger.info(f"🕸️ Web Server started on port {PORT}")

# ================= BOT COMMANDS =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    
    # Beautiful Welcome Message
    welcome_text = (
        f"🌟 <b> Konnichiwa, {user.first_name}!</b> 🌟\n\n"
        f"Welcome to the <b>Ultimate Anime Broadcast Bot</b>.\n\n"
        f"🤖 <b>What do I do?</b>\n"
        f"• I deliver the hottest Anime recommendations every 10 minutes.\n"
        f"• I notify you about updates from <b>{CHANNEL_NAME}</b>.\n"
        f"• I bring you direct links to watch your favorite shows.\n\n"
        f"✨ <i>Sit back, relax, and let the anime come to you!</i>"
    )

    if chat.type == 'private':
        await register_user(chat.id)
        await update.message.reply_text(welcome_text, parse_mode=ParseMode.HTML)
    else:
        await register_group(chat.id, chat.title)
        await update.message.reply_text("✅ <b>Bot Activated!</b> Ready to serve this group.", parse_mode=ParseMode.HTML)

async def admin_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    
    active, inactive, groups = await get_stats()
    text = (
        f"📊 <b>ADMIN DASHBOARD</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"✅ <b>Active Users:</b> {active}\n"
        f"❌ <b>Blocked Users:</b> {inactive}\n"
        f"👥 <b>Groups:</b> {groups}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"<b>Commands:</b>\n"
        f"<code>/broadcast</code> (reply to message)\n"
        f"<code>/schedule 60</code> (reply to message)\n"
        f"<code>/setlink Naruto | https://t.me/post/1</code>\n"
        f"<code>/deletelink Naruto</code>"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

async def set_anime_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Usage: /setlink naruto | https://t.me/c/123/456"""
    if update.effective_user.id != ADMIN_ID: return
    try:
        raw_text = ' '.join(context.args)
        name, link = raw_text.split('|')
        name = name.strip().lower()
        link = link.strip()
        
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("INSERT OR REPLACE INTO anime_links VALUES (?, ?)", (name, link))
            await db.commit()
        await update.message.reply_text(f"✅ Link saved! When MAL finds '{name}', it will link to: {link}")
    except ValueError:
        await update.message.reply_text("❌ Format: `/setlink Anime Name | https://t.me/link`", parse_mode=ParseMode.MARKDOWN)

async def delete_anime_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Usage: /deletelink naruto
    Deletes the custom link for the specified anime.
    """
    if update.effective_user.id != ADMIN_ID: return
    
    # 1. Get the anime name from the message
    anime_name = ' '.join(context.args).strip().lower()
    
    if not anime_name:
        await update.message.reply_text("❌ Usage: `/deletelink <anime_name>`", parse_mode=ParseMode.MARKDOWN)
        return

    # 2. Remove it from the database
    async with aiosqlite.connect(DB_NAME) as db:
        # Check if it exists first
        cursor = await db.execute("SELECT * FROM anime_links WHERE anime_name = ?", (anime_name,))
        data = await cursor.fetchone()
        
        if not data:
            await update.message.reply_text(f"⚠️ No link found for **{anime_name}**.", parse_mode=ParseMode.MARKDOWN)
            return
        
        # If found, delete it
        await db.execute("DELETE FROM anime_links WHERE anime_name = ?", (anime_name,))
        await db.commit()
    
    await update.message.reply_text(f"🗑️ **Deleted!** The custom link for '{anime_name}' has been removed.", parse_mode=ParseMode.MARKDOWN)

# ================= BROADCAST ENGINE =================

async def broadcast_logic(application, from_chat_id, message_id):
    targets = await get_all_chats()
    sent = 0
    blocked = 0
    
    for chat_id in targets:
        try:
            await application.bot.copy_message(chat_id=chat_id, from_chat_id=from_chat_id, message_id=message_id)
            sent += 1
        except Forbidden:
            await mark_inactive(chat_id)
            blocked += 1
        except Exception as e:
            logger.warning(f"Failed to send to {chat_id}: {e}")
        
        await asyncio.sleep(0.05) # Prevent flood limits

    return sent, blocked

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    
    reply = update.message.reply_to_message
    if not reply:
        await update.message.reply_text("⚠️ Please reply to a message (text, video, photo) to broadcast it.")
        return

    status_msg = await update.message.reply_text("🚀 Broadcasting started...")
    sent, blocked = await broadcast_logic(context.application, update.effective_chat.id, reply.message_id)
    await status_msg.edit_text(f"✅ <b>Broadcast Complete</b>\n\nUnknown received: {sent}\nBlocked/Kicked: {blocked}", parse_mode=ParseMode.HTML)

# ================= SCHEDULING SYSTEM =================

async def execute_schedule(context: ContextTypes.DEFAULT_TYPE):
    job_data = context.job.data
    await broadcast_logic(context.application, job_data['chat_id'], job_data['msg_id'])
    # Notify admin
    await context.bot.send_message(job_data['chat_id'], "⏰ Scheduled Post has been sent!")

async def schedule_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Usage: /schedule 10 (schedules post for 10 mins later)"""
    if update.effective_user.id != ADMIN_ID: return
    
    reply = update.message.reply_to_message
    if not reply:
        await update.message.reply_text("⚠️ Reply to a message to schedule it.")
        return

    try:
        minutes = int(context.args[0])
        context.job_queue.run_once(
            execute_schedule, 
            when=minutes * 60,
            data={'chat_id': update.effective_chat.id, 'msg_id': reply.message_id}
        )
        run_time = datetime.now() + timedelta(minutes=minutes)
        await update.message.reply_text(f"✅ Message scheduled for {run_time.strftime('%H:%M')} ({minutes} mins).")
    except (IndexError, ValueError):
        await update.message.reply_text("❌ Usage: `/schedule <minutes>`", parse_mode=ParseMode.MARKDOWN)

# ================= AI AUTO-POST (ANILIST GRAPHQL) =================

async def auto_blog_job(context: ContextTypes.DEFAULT_TYPE):
    """Runs every 10 minutes to fetch and post anime using AniList GraphQL."""
    
    # 1. Setup AniList GraphQL Query
    url = 'https://graphql.anilist.co'
    random_page = random.randint(1, 50) # Pick a random page of popular anime
    
    query = '''
    query ($page: Int) {
      Page (page: $page, perPage: 1) {
        media (type: ANIME, sort: POPULARITY_DESC) {
          title { romaji english }
          coverImage { extraLarge }
          bannerImage
          description
          averageScore
          siteUrl
        }
      }
    }
    '''
    
    try:
        # 2. Fetch Data from AniList
        async with ClientSession() as session:
            async with session.post(url, json={'query': query, 'variables': {'page': random_page}}) as resp:
                data = await resp.json()
                anime = data['data']['Page']['media'][0]

        if not anime: return

        # 3. Extract & Format Details
        title_romaji = anime['title']['romaji']
        title_english = anime['title']['english']
        
        # Prefer English title if available, else Romaji
        final_title = title_english if title_english else title_romaji
        
        score = anime.get('averageScore', 'N/A')
        if score != 'N/A': score = f"{score}%" # AniList uses 0-100
        
        # Clean HTML from description
        synopsis = anime.get('description', 'No description available.')
        if synopsis:
            synopsis = synopsis.replace('<br>', '\n').replace('<i>', '').replace('</i>', '')
        
        # Shorten synopsis
        if len(synopsis) > 400: synopsis = synopsis[:400] + "..."

        # 4. Image Logic (Prefer Banner, Fallback to Poster)
        image_url = anime.get('bannerImage')
        if not image_url:
            image_url = anime['coverImage']['extraLarge']
            
        site_url = anime.get('siteUrl', '')

        # 5. Check Custom Link in Database
        channel_link = await get_custom_link(final_title)
        if not channel_link and title_romaji:
             channel_link = await get_custom_link(title_romaji)

        # 6. Build Caption
        caption = f"🎬 <b>{final_title}</b>"
        if title_english and title_english != title_romaji: 
            caption += f" ({title_romaji})"
        caption += "\n━━━━━━━━━━━━━━━━━━\n"
        caption += f"⭐ <b>Rating:</b> {score}\n"
        caption += f"📝 <b>Description:</b> {synopsis}\n\n"

        if channel_link:
            caption += f"📺 <b>WATCH HERE: <a href='{channel_link}'>{CHANNEL_NAME}</a></b>\n"
        else:
            caption += f"📺 <b>Where to watch:</b> Check <a href='{site_url}'>AniList</a>\n"

        caption += "\n━━━━━━━━━━━━━━━━━━\n"
        caption += f"📣 Ads sponsored by <b><a href='{CHANNEL_LINK}'>{CHANNEL_NAME}</a></b>\n"
        caption += f"⚠️ <i>We do not do any copyright thing but only gives recommendation to subscribers to watch it.</i>"

        # 7. Broadcast
        targets = await get_all_chats()
        for chat_id in targets:
            try:
                await context.bot.send_photo(
                    chat_id=chat_id, 
                    photo=image_url, 
                    caption=caption, 
                    parse_mode=ParseMode.HTML
                )
            except Exception:
                pass # Ignore errors during auto-post (e.g., user blocked)

    except Exception as e:
        logger.error(f"Auto-Blog Error: {e}")

# ================= MAIN ENTRY POINT =================

def main():
    # 1. Initialize DB
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(init_db())

    # 2. Build Bot
    application = Application.builder().token(TOKEN).build()

    # 3. Add Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin", admin_dashboard))
    application.add_handler(CommandHandler("broadcast", broadcast_command))
    application.add_handler(CommandHandler("schedule", schedule_command))
    application.add_handler(CommandHandler("setlink", set_anime_link))
    application.add_handler(CommandHandler("deletelink", delete_anime_link)) # <--- ADDED HERE
    
    # Track when bot is added to groups
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, start))

    # 4. Schedule Auto-Blog (Every 10 Minutes = 600s)
    application.job_queue.run_repeating(auto_blog_job, interval=600, first=10)

    # 5. Start Web Server (For Render/Port requirement)
    loop.create_task(start_web_server())

    # 6. Run Bot
    print("🚀 Bot is running with Web Server...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()

```
