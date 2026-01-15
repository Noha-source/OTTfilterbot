import logging
import sqlite3
import requests
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, ContextTypes, CommandHandler, 
    MessageHandler, filters, CallbackQueryHandler
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# --- CONFIGURATION ---
BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
TMDB_API_KEY = "YOUR_TMDB_API_KEY"
ADMIN_ID = 123456789  # Replace with your numeric Telegram ID
DB_FILE = "bot_users.db"

# --- ADVERTISING CONFIG ---
# This text is attached to every automatic post
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

# --- DATABASE FUNCTIONS (User Management) ---
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
    """Fetches content from TMDB (Trending or Upcoming)."""
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
    """Formats the movie details into a blog-style post."""
    title = item.get('title') or item.get('name')
    overview = item.get('overview', 'No description available.')
    # Truncate long descriptions
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

# --- AUTOMATIC BROADCASTING SYSTEM ---
async def auto_broadcast(context: ContextTypes.DEFAULT_TYPE):
    """Sends 2 posts every cycle to all users."""
    logger.info("Starting Auto-Broadcast...")
    users = get_all_users()
    
    # Fetch content (Mix of Trending and Upcoming)
    trending = await fetch_tmdb_content("trending/all/day")
    upcoming = await fetch_tmdb_content("movie/upcoming")
    
    # Select 2 distinct items to post
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
                await asyncio.sleep(0.5) # Prevent hitting Telegram limits
            except Exception as e:
                logger.warning(f"Failed to send to {user_id}: {e}") # Usually user blocked bot

# --- BOT HANDLERS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if check_ban(user_id): return # Ignore banned users
    
    add_user(user_id) # Save subscriber
    
    await update.message.reply_text(
        "👋 *Welcome to the Ultimate OTT Hub!*\n\n"
        "I provide updates on Netflix, Prime, Ullu, MoodX, and more.\n"
        "You are now subscribed to auto-updates every 20 mins.\n\n"
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

    # Check Niche Platforms First
    for key, platform_name in NICHE_PLATFORMS.items():
        if key in query.lower():
            await update.message.reply_text(
                f"🎬 *{query.title()}*\n"
                f"📺 *Available On:* {platform_name}\n"
                f"⚠️ *Note:* This is a niche platform content.",
                parse_mode='Markdown'
            )
            return

    # Check TMDB
    url = f"https://api.themoviedb.org/3/search/multi?api_key={TMDB_API_KEY}&query={query}"
    response = requests.get(url).json()
    results = response.get('results', [])

    if not results:
        await update.message.reply_text("❌ No results found on major or niche platforms.")
        return

    item = results[0]
    caption, img_url = format_media_message(item)
    
    keyboard = [[InlineKeyboardButton("📺 Watch Options", url="https://google.com")]] # Placeholder link
    
    if img_url:
        await update.message.reply_photo(photo=img_url, caption=caption, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(caption, parse_mode='Markdown')

# --- ADMIN COMMANDS ---

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    users = get_all_users()
    await update.message.reply_text(f"📊 **Total Subscribers:** {len(users)}")

async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        target_id = int(context.args[0])
        ban_user_db(target_id, True)
        await update.message.reply_text(f"🚫 User {target_id} BANNED.")
    except:
        await update.message.reply_text("Usage: /ban 123456789")

async def unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        target_id = int(context.args[0])
        ban_user_db(target_id, False)
        await update.message.reply_text(f"✅ User {target_id} UNBANNED.")
    except:
        await update.message.reply_text("Usage: /unban 123456789")

# --- MAIN SETUP ---
if __name__ == '__main__':
    # 1. Initialize Database
    init_db()
    
    # 2. Build Application
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    
    # 3. Add Handlers
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('search', search_handler))
    application.add_handler(CommandHandler('stats', stats))
    application.add_handler(CommandHandler('ban', ban))
    application.add_handler(CommandHandler('unban', unban))

    # 4. Setup Scheduler (Auto-Post every 20 mins)
    scheduler = AsyncIOScheduler()
    # Add job to run every 20 minutes
    scheduler.add_job(auto_broadcast, 'interval', minutes=20, args=[application])
    scheduler.start()

    print("🤖 Bot with Auto-Ads & Admin Tools is Running...")
    application.run_polling()
