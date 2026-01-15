import logging
import sqlite3
import requests
import asyncio
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, ContextTypes, CommandHandler, 
    MessageHandler, filters, CallbackQueryHandler
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# --- CONFIGURATION (Using Environment Variables) ---
# Set these in the Render Dashboard under "Environment"
BOT_TOKEN = os.getenv("BOT_TOKEN")
TMDB_API_KEY = os.getenv("TMDB_API_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0")) 
DB_FILE = "bot_users.db"

# --- ADVERTISING CONFIG ---
SPONSORED_TEXT = (
    "\n\n---------------------------------\n"
    "📢 *SPONSORED: Join @MyChannel for leaks!*\n"
    "👉 [Click Here to Watch Free](https://google.com)\n"
    "---------------------------------"
)

# --- NICHE PLATFORMS DATABASE ---
NICHE_PLATFORMS = {
    "ullu": "🦉 Ullu", "altbalaji": "💠 AltBalaji", "zee5": "🦓 Zee5",
    "rabbit": "🐰 Rabbit", "uncut": "✂ Uncut", "bindaas": "🅱 Bindaas",
    "nueflicks": "🆕 Nuefliks", "moodx": "😈 MoodX", "prime play": "▶ Prime Play",
    "tri flicks": "🔺 Tri Flicks", "xtramood": "✖ Xtramood", "navarasa": "🎭 Navarasa",
    "dreams film": "💭 Dreams Film", "nonex": "🚫 Nonex"
}

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- DATABASE FUNCTIONS ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (user_id INTEGER PRIMARY KEY, is_banned BOOLEAN DEFAULT 0)''')
    conn.commit()
    conn.close()

def add_user(user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    try:
        c.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
        conn.commit()
    except Exception as e:
        logger.error(f"DB Error: {e}")
    finally:
        conn.close()

def get_all_users():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE is_banned = 0")
    users = [row[0] for row in c.fetchall()]
    conn.close()
    return users

def ban_user_db(user_id, status=True):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE users SET is_banned = ? WHERE user_id = ?", (status, user_id))
    conn.commit()
    conn.close()

def check_ban(user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT is_banned FROM users WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else False

# --- TMDB & CONTENT FUNCTIONS ---
async def fetch_tmdb_content(endpoint="trending/all/day"):
    url = f"https://api.themoviedb.org/3/{endpoint}"
    params = {"api_key": TMDB_API_KEY, "language": "en-US", "page": 1}
    try:
        response = requests.get(url, params=params)
        data = response.json()
        return data.get('results', [])
    except Exception as e:
        logger.error(f"API Error: {e}")
        return []

def format_media_message(item, is_auto_post=False):
    title = item.get('title') or item.get('name')
    overview = item.get('overview', 'No description available.')
    if len(overview) > 300: overview = overview[:300] + "..."
    
    media_type = item.get('media_type', 'Movie').upper()
    rating = item.get('vote_average', 'N/A')
    release = item.get('release_date') or item.get('first_air_date') or "Coming Soon"
    poster_path = item.get('poster_path')
    
    img_url = f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else None
    
    caption = (
        f"🔥 *{title}* ({release[:4]})\n"
        f"🌟 *Rating:* {rating}/10\n"
        f"📺 *Category:* {media_type}\n\n"
        f"📖 *Storyline:*\n{overview}\n"
    )
    if is_auto_post:
        caption += SPONSORED_TEXT
    return caption, img_url

# --- AUTOMATIC BROADCASTING ---
async def auto_broadcast(context: ContextTypes.DEFAULT_TYPE):
    logger.info("Starting Auto-Broadcast...")
    users = get_all_users()
    trending = await fetch_tmdb_content("trending/all/day")
    upcoming = await fetch_tmdb_content("movie/upcoming")
    
    items_to_post = []
    if trending: items_to_post.append(trending[0])
    if upcoming: items_to_post.append(upcoming[0])
    
    for item in items_to_post:
        caption, img_url = format_media_message(item, is_auto_post=True)
        for user_id in users:
            try:
                if img_url:
                    await context.bot.send_photo(chat_id=user_id, photo=img_url, caption=caption, parse_mode='Markdown')
                else:
                    await context.bot.send_message(chat_id=user_id, text=caption, parse_mode='Markdown')
                await asyncio.sleep(0.5) 
            except Exception as e:
                logger.warning(f"Failed to send to {user_id}: {e}")

# --- BOT HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if check_ban(user_id): return
    add_user(user_id)
    await update.message.reply_text(
        "👋 *Welcome to the Ultimate OTT Hub!*\n\n"
        "I provide updates on Netflix, Prime, Ullu, MoodX, and more.\n"
        "**Commands:**\n"
        "/search <name> - Find where to watch\n"
        "/upcoming - List upcoming movies\n"
        "/trending - What's hot right now",
        parse_mode='Markdown'
    )

async def search_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if check_ban(user_id): return
    query = " ".join(context.args)
    if not query:
        await update.message.reply_text("🔎 Usage: `/search Mirzapur`")
        return

    # Check Niche Platforms
    for key, platform_name in NICHE_PLATFORMS.items():
        if key in query.lower():
            await update.message.reply_text(
                f"🎬 *{query.title()}*\n📺 *Available On:* {platform_name}",
                parse_mode='Markdown'
            )
            return

    # Check TMDB
    url = f"https://api.themoviedb.org/3/search/multi?api_key={TMDB_API_KEY}&query={query}"
    response = requests.get(url).json()
    results = response.get('results', [])

    if not results:
        await update.message.reply_text("❌ No results found.")
        return

    item = results[0]
    caption, img_url = format_media_message(item)
    keyboard = [[InlineKeyboardButton("📺 Watch Options", url="https://google.com")]]
    
    if img_url:
        await update.message.reply_photo(photo=img_url, caption=caption, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(caption, parse_mode='Markdown')

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    users = get_all_users()
    await update.message.reply_text(f"📊 **Total Subscribers:** {len(users)}")

# --- MAIN ---
if __name__ == '__main__':
    init_db()
    if not BOT_TOKEN:
        print("Error: BOT_TOKEN not found in environment variables.")
        exit(1)
        
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('search', search_handler))
    application.add_handler(CommandHandler('stats', stats))

    scheduler = AsyncIOScheduler()
    scheduler.add_job(auto_broadcast, 'interval', minutes=20, args=[application])
    scheduler.start()

    print("🤖 Bot is Running...")
    application.run_polling()
    
