import logging
import sqlite3
import requests
import asyncio
import os
import threading
import http.server
import socketserver
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, ContextTypes, CommandHandler, 
    MessageHandler, filters, CallbackQueryHandler
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# --- CONFIGURATION (Render Environment Variables) ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
TMDB_API_KEY = os.getenv("TMDB_API_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0")) 
DB_FILE = "bot_users.db"
# Render automatically provides a PORT environment variable
PORT = int(os.getenv("PORT", "8080")) 

# --- KEEP-ALIVE HEALTH SERVER ---
# This server satisfies Render's port scan to keep the service active.
def run_health_server():
    class HealthHandler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Bot is alive!")

    # Allowing address reuse helps avoid 'Port already in use' errors during restarts
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", PORT), HealthHandler) as httpd:
        print(f"✅ Health server satisfying Render port scan on port {PORT}")
        httpd.serve_forever()

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
        "👋 *Welcome to OTT Hub!*\n\n"
        "I provide updates on Netflix, Prime, Ullu, and more.\n"
        "**Commands:**\n"
        "/search <name> - Find movies\n"
        "/trending - What's hot right now",
        parse_mode='Markdown'
    )

# --- MAIN SETUP ---
if __name__ == '__main__':
    init_db()
    
    if not BOT_TOKEN:
        print("CRITICAL ERROR: BOT_TOKEN environment variable not set.")
        exit(1)

    # 1. Start the Health Server in a separate thread so it doesn't block the bot
    threading.Thread(target=run_health_server, daemon=True).start()
        
    # 2. Build the Application
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler('start', start))

    # 3. Setup Scheduler
    scheduler = AsyncIOScheduler()
    scheduler.add_job(auto_broadcast, 'interval', minutes=20, args=[application])
    scheduler.start()

    print("🤖 Bot is active, health server running, and polling started...")
    # drop_pending_updates=True helps resolve the Conflict error from simultaneous requests
    application.run_polling(drop_pending_updates=True)
