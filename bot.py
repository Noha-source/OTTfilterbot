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

# --- CONFIGURATION (Render Environment Variables) ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
TMDB_API_KEY = os.getenv("TMDB_API_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0")) 
DB_FILE = "bot_users.db"
PORT = int(os.getenv("PORT", "8080")) 

# --- KEEP-ALIVE HEALTH SERVER ---
# This satisfies Render's port scan to keep the service active.
def run_health_server():
    class HealthHandler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Bot is alive!")

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
    if len(overview) > 300: overview = overview[:300] + "... "
    
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
    return caption, img
