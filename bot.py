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
CHANNEL_NAME = os.getenv('CHANNEL_NAME', 'My Anime Channel')
CHANNEL_LINK = os.getenv('CHANNEL_LINK', 'https://t.me/your_channel_link')
PORT = int(os.getenv('PORT', 8080))
DB_NAME = "bot_data.db"

# --- ANILIST API KEY ---
ANILIST_API_KEY = 'Tc7EZODlyrHc5ZuDps3Jr4JWsxWCqoqzFbrPWJzr'

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

# ================= ANILIST API ENGINE =================
async def fetch_random_anilist_data():
    url = 'https://graphql.anilist.co'
    random_page = random.randint(1, 50) 
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
    headers = {
        'Authorization': f'Bearer {ANILIST_API_KEY}',
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }
    async with ClientSession() as session:
        try:
            async with session.post(url, json={'query': query, 'variables': {'page': random_page}}, headers=headers) as resp:
                if resp.status != 200:
                    logger.error(f"AniList API Error {resp.status}")
                    return None
                data = await resp.json()
                media = data['data']['Page']['media']
                return media[0] if media else None
        except Exception as e:
            logger.error(f"AniList Connection Error: {e}")
            return None

# ================= AUTO POST LOGIC =================
async def send_anime_post(bot, chat_id):
    """Helper function to send a post to a specific chat."""
    anime = await fetch_random_anilist_data()
    if not anime: return

    title_romaji = anime['title']['romaji']
    title_english = anime['title']['english']
    final_title = title_english if title_english else title_romaji
    
    score = anime.get('averageScore', 'N/A')
    if score != 'N/A': score = f"{score}%"
    
    desc = anime.get('description', 'No description available.')
    if desc:
        desc = desc.replace('<br>', '\n').replace('<i>', '').replace('</i>', '')
    if len(desc) > 350: desc = desc[:350] + "..."

    image_url = anime.get('bannerImage') or anime['coverImage']['extraLarge']
    site_url = anime.get('siteUrl')

    channel_link = await get_custom_link(final_title) or await get_custom_link(title_romaji)

    caption = f"🎬 <b>{final_title}</b>\n"
    if title_english and title_english != title_romaji:
        caption += f"<i>({title_romaji})</i>\n"
    
    caption += f"━━━━━━━━━━━━━━━━━━\n"
    caption += f"⭐ <b>Rating:</b> {score}\n"
    caption += f"📝 <b>Story:</b> {desc}\n\n"

    if channel_link:
        caption += f"📺 <b>WATCH HERE: <a href='{channel_link}'>{CHANNEL_NAME}</a></b>\n"
    else:
        caption += f"📺 <b>Where to watch:</b> Check <a href='{site_url}'>AniList</a>\n"

    caption += f"\n━━━━━━━━━━━━━━━━━━\n"
    caption += f"📣 Ads sponsored by <b><a href='{CHANNEL_LINK}'>{CHANNEL_NAME}</a></b>\n"
    caption += f"⚠️ <i>We do not do any copyright thing but only gives recommendation to subscribers to watch it.</i>"

    try:
        await bot.send_photo(chat_id=chat_id, photo=image_url, caption=caption, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error(f"Error sending post to {chat_id}: {e}")

async def auto_blog_job(context: ContextTypes.DEFAULT_TYPE):
    """The background job for all users every 10 mins."""
    targets = await get_all_chats()
    for chat_id in targets:
        await send_anime_post(context.bot, chat_id)

# ================= COMMANDS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    welcome_text = (
        "🌟 <b>Konnichiwa,</b> 🌟\n\n"
        "Welcome to the <b>Ultimate Anime Broadcast Bot</b>.\n\n"
        "🤖 <b>What do I do?</b>\n"
        "• I deliver the hottest Anime recommendations every 10 minutes.\n"
        "✨ <i>Sit back, relax, and let the anime come to you!</i>"
    )

    # 1. Register User/Group in Database
    if chat.type == 'private':
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (chat.id,))
            await db.execute("UPDATE users SET status='active' WHERE user_id=?", (chat.id,))
            await db.commit()
    else:
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("INSERT OR IGNORE INTO groups (chat_id, title) VALUES (?, ?)", (chat.id, chat.title))
            await db.commit()

    # 2. Send Welcome Message
    await update.message.reply_text(welcome_text, parse_mode=ParseMode.HTML)
    
    # 3. IMMEDIATELY send the first random anime post
    await update.message.reply_text("🚀 <b>Fetching your first recommendation...</b>", parse_mode=ParseMode.HTML)
    await send_anime_post(context.bot, chat.id)

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
    application.add_handler(CommandHandler("broadcast", broadcast_command))
    application.add_handler(CommandHandler("setlink", set_anime_link))
    application.add_handler(CommandHandler("deletelink", delete_anime_link))
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, start))

    if application.job_queue:
        application.job_queue.run_repeating(auto_blog_job, interval=600, first=10)
        logger.info("Auto-post job scheduled.")
    else:
        logger.error("JobQueue unavailable.")

    await start_web_server()

    async with application:
        await application.initialize()
        await application.start()
        await application.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        logger.info(f"🚀 Bot is running on port {PORT}...")
        while True:
            await asyncio.sleep(1)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
