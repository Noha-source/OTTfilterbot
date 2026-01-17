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
    """
    Fetches a random anime from AniList using the provided API Key.
    """
    url = 'https://graphql.anilist.co'
    
    # Logic: Pick a random page (1-50) of 'Most Popular' anime to get high-quality recommendations
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
    
    # Headers with your API Key
    headers = {
        'Authorization': f'Bearer {ANILIST_API_KEY}',
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }

    async with ClientSession() as session:
        try:
            async with session.post(url, json={'query': query, 'variables': {'page': random_page}}, headers=headers) as resp:
                if resp.status != 200:
                    logger.error(f"AniList API Error {resp.status}: Check if API Key is valid.")
                    return None
                    
                data = await resp.json()
                media = data['data']['Page']['media']
                if media:
                    return media[0]
                return None
        except Exception as e:
            logger.error(f"AniList Connection Error: {e}")
            return None

# ================= AUTO POST JOB =================
async def auto_blog_job(context: ContextTypes.DEFAULT_TYPE):
    """The function that runs automatically every 10 minutes."""
    
    # 1. Get Anime Data
    anime = await fetch_random_anilist_data()
    if not anime: return

    # 2. Extract Info
    title_romaji = anime['title']['romaji']
    title_english = anime['title']['english']
    final_title = title_english if title_english else title_romaji
    
    score = anime.get('averageScore', 'N/A')
    if score != 'N/A': score = f"{score}%"
    
    # Clean up description (Remove HTML tags like <br>)
    desc = anime.get('description', 'No description available.')
    if desc:
        desc = desc.replace('<br>', '\n').replace('<i>', '').replace('</i>', '')
    if len(desc) > 350: desc = desc[:350] + "..."

    # Use Wide Banner if available, else Poster
    image_url = anime.get('bannerImage') or anime['coverImage']['extraLarge']
    site_url = anime.get('siteUrl')

    # 3. Database Check (Your Custom Links)
    channel_link = await get_custom_link(final_title)
    if not channel_link and title_romaji:
         channel_link = await get_custom_link(title_romaji)

    # 4. Create Post
    caption = f"🎬 <b>{final_title}</b>\n"
    if title_english and title_english != title_romaji:
        caption += f"<i>({title_romaji})</i>\n"
    
    caption += f"━━━━━━━━━━━━━━━━━━\n"
    caption += f"⭐ <b>Rating:</b> {score}\n"
    caption += f"📝 <b>Story:</b> {desc}\n\n"

    # Where to watch logic
    if channel_link:
        caption += f"📺 <b>WATCH HERE: <a href='{channel_link}'>{CHANNEL_NAME}</a></b>\n"
    else:
        caption += f"📺 <b>Where to watch:</b> Check <a href='{site_url}'>AniList</a>\n"

    caption += f"\n━━━━━━━━━━━━━━━━━━\n"
    caption += f"📣 Ads sponsored by <b><a href='{CHANNEL_LINK}'>{CHANNEL_NAME}</a></b>\n"
    caption += f"⚠️ <i>We do not do any copyright thing but only gives recommendation to subscribers to watch it.</i>"

    # 5. Broadcast
    targets = await get_all_chats()
    for chat_id in targets:
        try:
            await context.bot.send_photo(chat_id=chat_id, photo=image_url, caption=caption, parse_mode=ParseMode.HTML)
        except Exception:
            pass 

# ================= COMMANDS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    
    # --- UPDATED WELCOME MESSAGE ---
    welcome_text = (
        "🌟 <b>Konnichiwa,</b> 🌟\n\n"
        "Welcome to the <b>Ultimate Anime Broadcast Bot</b>.\n\n"
        "🤖 <b>What do I do?</b>\n"
        "• I deliver the hottest Anime recommendations every 10 minutes.\n"
        "• I notify you about updates from <b>MY ANIME ENGLISH DUB</b>.\n"
        "• I bring you direct links to watch your favorite shows.\n\n"
        "✨ <i>Sit back, relax, and let the anime come to you!</i>"
    )

    if chat.type == 'private':
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (chat.id,))
            await db.execute("UPDATE users SET status='active' WHERE user_id=?", (chat.id,))
            await db.commit()
        await update.message.reply_text(welcome_text, parse_mode=ParseMode.HTML)
