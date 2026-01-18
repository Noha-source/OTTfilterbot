import logging
import asyncio
import os
import sys
import random
from datetime import datetime, timedelta
from aiohttp import web, ClientSession
import aiosqlite
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
from telegram.constants import ParseMode
from telegram.error import Forbidden

# ================= CONFIGURATION =================
TOKEN = os.getenv('TOKEN', 'YOUR_BOT_TOKEN_HERE') 
ADMIN_ID = int(os.getenv('ADMIN_ID', '123456789')) 
# New Config for specific channel scheduling
MAIN_CHANNEL_ID = int(os.getenv('MAIN_CHANNEL_ID', '-1001234567890')) 
CHANNEL_NAME = os.getenv('CHANNEL_NAME', 'My Anime Channel')
CHANNEL_LINK = os.getenv('CHANNEL_LINK', 'https://t.me/your_channel_link')
PORT = int(os.getenv('PORT', 8080))
DB_NAME = "bot_data.db"

# ================= LOGGING =================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ================= DATABASE MANAGER =================
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, status TEXT DEFAULT 'active')''')
        await db.execute('''CREATE TABLE IF NOT EXISTS groups (chat_id INTEGER PRIMARY KEY, title TEXT)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS anime_links (anime_name TEXT PRIMARY KEY, post_link TEXT)''')
        # NEW: Table for scheduled posts
        await db.execute('''CREATE TABLE IF NOT EXISTS scheduled_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            message_id INTEGER,
            run_date TEXT,
            target_mode TEXT
        )''')
        await db.commit()

async def get_all_chats():
    async with aiosqlite.connect(DB_NAME) as db:
        users = await db.execute_fetchall("SELECT user_id FROM users WHERE status='active'")
        groups = await db.execute_fetchall("SELECT chat_id FROM groups")
        return [row[0] for row in users] + [row[0] for row in groups]

async def mark_inactive(user_id):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE users SET status='inactive' WHERE user_id=?", (user_id,))
        await db.commit()

async def get_custom_link(anime_title):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT post_link FROM anime_links WHERE ? LIKE '%' || anime_name || '%'", (anime_title.lower(),))
        row = await cursor.fetchone()
        return row[0] if row else None

# ================= ANILIST GRAPHQL API ENGINE =================
async def fetch_random_anime_data():
    url = 'https://graphql.anilist.co'
    random_page = random.randint(1, 100) 
    query = '''
    query ($page: Int) {
      Page (page: $page, perPage: 1) {
        media (type: ANIME, sort: POPULARITY_DESC) {
          title { romaji english native }
          coverImage { extraLarge }
          bannerImage
          description
          averageScore
          siteUrl
        }
      }
    }
    '''
    async with ClientSession() as session:
        try:
            async with session.post(url, json={'query': query, 'variables': {'page': random_page}}) as resp:
                if resp.status != 200:
                    logger.error(f"AniList API Error {resp.status}")
                    return None
                res_json = await resp.json()
                media = res_json.get('data', {}).get('Page', {}).get('media')
                if not media: return None
                data = media[0]
                return {
                    'title': data['title'].get('english') or data['title'].get('romaji'),
                    'title_japanese': data['title'].get('native'),
                    'image': data.get('bannerImage') or data.get('coverImage', {}).get('extraLarge'),
                    'score': data.get('averageScore'),
                    'synopsis': data.get('description'),
                    'url': data.get('siteUrl')
                }
        except Exception as e:
            logger.error(f"AniList Connection Error: {e}")
            return None

# ================= AUTO POST LOGIC =================
async def send_anime_post(bot, chat_id):
    anime = await fetch_random_anime_data()
    if not anime: return
    title = anime['title']
    title_jp = anime['title_japanese']
    score = f"{anime['score']}%" if anime['score'] else "N/A"
    desc = anime['synopsis'] or "No description available."
    if desc:
        desc = desc.replace('<br>', '\n').replace('<i>', '').replace('</i>', '').replace('<b>', '').replace('</b>', '')
    if len(desc) > 350: desc = desc[:350] + "..."
    image_url = anime['image']
    site_url = anime['url']
    channel_link = await get_custom_link(title) or await get_custom_link(title_jp)
    caption = f"🎬 <b>{title}</b>\n"
    if title_jp:
        caption += f"<i>({title_jp})</i>\n"
    caption += f"━━━━━━━━━━━━━━━━━━\n⭐ <b>Rating:</b> {score}\n📝 <b>Story:</b> {desc}\n\n"
    if channel_link:
        caption += f"📺 <b>WATCH HERE: <a href='{channel_link}'>{CHANNEL_NAME}</a></b>\n"
    else:
        caption += f"📺 <b>Where to watch:</b> Check <a href='{site_url}'>AniList</a>\n"
    caption += f"\n━━━━━━━━━━━━━━━━━━\n📣 Ads sponsored by <b><a href='{CHANNEL_LINK}'>{CHANNEL_NAME}</a></b>\n"
    caption += f"⚠️ <i>We do not do any copyright thing but only gives recommendation to subscribers to watch it.</i>"
    try:
        await bot.send_photo(chat_id=chat_id, photo=image_url, caption=caption, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error(f"Error sending post to {chat_id}: {e}")

async def auto_blog_job(context: ContextTypes.DEFAULT_TYPE):
    targets = await get_all_chats()
    for chat_id in targets:
        await send_anime_post(context.bot, chat_id)
        await asyncio.sleep(1) 

# ================= SCHEDULER LOGIC (NEW) =================
async def schedule_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    
    reply = update.message.reply_to_message
    if not reply:
        await update.message.reply_text("❌ <b>Reply to a message to schedule it.</b>", parse_mode=ParseMode.HTML)
        return

    # Syntax: /schedule YYYY-MM-DD HH:MM [all/channel]
    try:
        args = context.args
        if len(args) < 2:
            raise ValueError("Not enough arguments")
        
        date_str = args[0]
        time_str = args[1]
        target_mode = args[2].lower() if len(args) > 2 else 'all' # Default to broadcast ALL
        
        # Validation
        if target_mode not in ['all', 'channel']:
            await update.message.reply_text("❌ Mode must be `all` (broadcast) or `channel` (single).")
            return

        run_date_str = f"{date_str} {time_str}"
        # Validate datetime format
        datetime.strptime(run_date_str, "%Y-%m-%d %H:%M")
        
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(
                "INSERT INTO scheduled_posts (chat_id, message_id, run_date, target_mode) VALUES (?, ?, ?, ?)",
                (update.effective_chat.id, reply.message_id, run_date_str, target_mode)
            )
            await db.commit()
            
        await update.message.reply_text(
            f"✅ <b>Post Scheduled!</b>\n\n"
            f"📅 <b>Time:</b> {run_date_str}\n"
            f"🎯 <b>Mode:</b> {target_mode.upper()}\n"
            f"(Will run when server time matches)",
            parse_mode=ParseMode.HTML
        )
    except ValueError:
        await update.message.reply_text(
            "❌ <b>Format Error!</b>\n"
            "Use: `/schedule YYYY-MM-DD HH:MM [all/channel]`\n"
            "Example: `/schedule 2024-05-20 14:30 all`", 
            parse_mode=ParseMode.HTML
        )

async def check_scheduled_posts_job(context: ContextTypes.DEFAULT_TYPE):
    """Checks DB every minute for posts that need to be sent"""
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    async with aiosqlite.connect(DB_NAME) as db:
        # Get posts where time is now or passed
        cursor = await db.execute("SELECT id, chat_id, message_id, target_mode FROM scheduled_posts WHERE run_date <= ?", (current_time,))
        posts = await cursor.fetchall()
        
        for post in posts:
            pid, from_chat_id, msg_id, mode = post
            
            # MODE: CHANNEL (Only post to Main Channel)
            if mode == 'channel':
                try:
                    await context.bot.copy_message(chat_id=MAIN_CHANNEL_ID, from_chat_id=from_chat_id, message_id=msg_id)
                except Exception as e:
                    logger.error(f"Failed to post schedule to channel: {e}")
            
            # MODE: ALL (Broadcast to Database Users + Groups)
            elif mode == 'all':
                targets = await get_all_chats()
                for chat_id in targets:
                    try:
                        await context.bot.copy_message(chat_id=chat_id, from_chat_id=from_chat_id, message_id=msg_id)
                        await asyncio.sleep(0.5) # Flood limit protection
                    except Forbidden:
                        await mark_inactive(chat_id)
                    except Exception as e:
                        logger.error(f"Scheduled broadcast fail for {chat_id}: {e}")

            # Delete processed post
            await db.execute("DELETE FROM scheduled_posts WHERE id = ?", (pid,))
        
        await db.commit()

# ================= COMMANDS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    
    # Safely get user name for HTML
    first_name = user.first_name.replace("<", "&lt;").replace(">", "&gt;") if user.first_name else "Senpai"

    # Attractive Font Style: Bold Headers, Monospace Lists, Italic Footer
    welcome_text = (
        f"🌟 <b>Konnichiwa, {first_name}!</b> 🌟\n\n"
        f"<b>Welcome to the Ultimate Anime Broadcast Bot.</b>\n\n"
        f"🤖 <b>What do I do?</b>\n"
        f"<code>• I deliver the hottest Anime recommendations every 10 minutes.</code>\n"
        f"<code>• I notify you about updates from {CHANNEL_NAME}.</code>\n"
        f"<code>• I bring you direct links to watch your favorite shows.</code>\n\n"
        f"✨ <i>Sit back, relax, and let the anime come to you!</i>"
    )

    if chat.type == 'private':
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (chat.id,))
            await db.execute("UPDATE users SET status='active' WHERE user_id=?", (chat.id,))
            await db.commit()
    else:
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("INSERT OR IGNORE INTO groups (chat_id, title) VALUES (?, ?)", (chat.id, chat.title))
            await db.commit()
    
    await update.message.reply_text(welcome_text, parse_mode=ParseMode.HTML)
    await update.message.reply_text("🚀 <b>Fetching your first wide-screen recommendation...</b>", parse_mode=ParseMode.HTML)
    await send_anime_post(context.bot, chat.id)

# NEW ADMIN STATS COMMAND
async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    async with aiosqlite.connect(DB_NAME) as db:
        active = await db.execute_fetchall("SELECT COUNT(*) FROM users WHERE status='active'")
        inactive = await db.execute_fetchall("SELECT COUNT(*) FROM users WHERE status='inactive'")
        groups = await db.execute_fetchall("SELECT COUNT(*) FROM groups")
        
        text = (
            "📊 <b>Bot Statistics</b>\n\n"
            f"✅ <b>Active Users:</b> {active[0][0]}\n"
            f"❌ <b>Inactive Users:</b> {inactive[0][0]}\n"
            f"👥 <b>Total Groups:</b> {groups[0][0]}\n"
            f"📈 <b>Total Reach:</b> {active[0][0] + groups[0][0]}"
        )
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)

async def set_anime_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        raw = ' '.join(context.args)
        name, link = raw.split('|')
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("INSERT OR REPLACE INTO anime_links VALUES (?, ?)", (name.strip().lower(), link.strip()))
            await db.commit()
        await update.message.reply_text(f"✅ Saved link for: {name.strip()}")
    except:
        await update.message.reply_text("❌ Format: `/setlink Name | Link`")

async def delete_anime_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    name = ' '.join(context.args).strip().lower()
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM anime_links WHERE anime_name = ?", (name,))
        await db.commit()
    await update.message.reply_text(f"🗑️ Deleted link for: {name}")

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    reply = update.message.reply_to_message
    if not reply: return await update.message.reply_text("Reply to a message to broadcast.")
    targets = await get_all_chats()
    for chat_id in targets:
        try:
            await context.bot.copy_message(chat_id, update.effective_chat.id, reply.message_id)
        except:
            await mark_inactive(chat_id)
    await update.message.reply_text("✅ Broadcast complete.")

# ================= WEB SERVER =================
async def health_check(request):
    return web.Response(text="Bot is ALIVE!")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()

# ================= MAIN =================
async def main():
    await init_db()
    application = Application.builder().token(TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stats", stats_command)) 
    application.add_handler(CommandHandler("broadcast", broadcast_command))
    # New Schedule Handler
    application.add_handler(CommandHandler("schedule", schedule_command))
    application.add_handler(CommandHandler("setlink", set_anime_link))
    application.add_handler(CommandHandler("deletelink", delete_anime_link))
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, start))

    if application.job_queue:
        # Existing Auto Blog Job
        application.job_queue.run_repeating(auto_blog_job, interval=600, first=10)
        # New Scheduler Check Job (Every 60 seconds)
        application.job_queue.run_repeating(check_scheduled_posts_job, interval=60, first=5)
        logger.info("Auto-post and Scheduler jobs active.")
    else:
        logger.error("JobQueue unavailable.")

    await start_web_server()
    async with application:
        await application.initialize()
        await application.start()
        await application.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        logger.info(f"🚀 Bot online on port {PORT}...")
        while True:
            await asyncio.sleep(1)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
