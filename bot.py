import logging
import requests
import asyncio
import os
import threading
import http.server
import socketserver
import random
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler
from pymongo import MongoClient

# --- CONFIGURATION ---
# Mapped to your Render Dashboard Environment Variables
BOT_TOKEN = os.getenv("BOT_TOKEN")
TMDB_API_KEY = os.getenv("TMDB_API_KEY")
PORT = int(os.getenv("PORT", "10000")) 
MONGO_URI = os.getenv("DB_FILE") # Using the 'DB_FILE' key from your dashboard
CHANNEL_LINK = os.getenv("CHANNEL_NAME") # Using the 'CHANNEL_NAME' key from your dashboard
ADMIN_ID = os.getenv("ADMIN_ID")

# --- MONGODB DATABASE SETUP ---
client = MongoClient(MONGO_URI)
db = client['OTT_Filter_Bot'] # Database name
users_col = db['users']      # Collection name

# --- KEEP-ALIVE HEALTH SERVER ---
def run_health_server():
    class HealthHandler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Bot Active")
    socketserver.TCPServer.allow_reuse_address = True
    # Binding to 0.0.0.0 is critical for Render
    with socketserver.TCPServer(("0.0.0.0", PORT), HealthHandler) as httpd:
        print(f"Health server serving on port {PORT}")
        httpd.serve_forever()

# --- DATABASE LOGIC (MONGODB) ---
def add_user(user_id):
    if not users_col.find_one({"user_id": user_id}):
        users_col.insert_one({"user_id": user_id})

def get_users():
    return [user['user_id'] for user in users_col.find()]

# --- ADVANCED TMDB FETCHING ---
def get_detailed_info(media_type, item_id):
    url = f"https://api.themoviedb.org/3/{media_type}/{item_id}?api_key={TMDB_API_KEY}&append_to_response=credits"
    try:
        data = requests.get(url).json()
        credits = data.get('credits', {})
        cast = ", ".join([m['name'] for m in credits.get('cast', [])[:3]])
        crew = credits.get('crew', [])
        director = ", ".join([m['name'] for m in crew if m['job'] == 'Director']) or "N/A"
        producer = ", ".join([m['name'] for m in crew if m['job'] == 'Producer'][:1]) or "N/A"
        return cast, director, producer
    except Exception as e:
        logging.error(f"TMDB Fetch Error: {e}")
        return "N/A", "N/A", "N/A"

# --- AUTOMATIC POST GENERATOR ---
async def send_auto_post(context: ContextTypes.DEFAULT_TYPE):
    url = f"https://api.themoviedb.org/3/trending/all/day?api_key={TMDB_API_KEY}"
    try:
        response = requests.get(url).json()
        results = response.get('results', [])
    except:
        return

    if not results: return

    item = random.choice(results[:10]) 
    m_type = item.get('media_type', 'movie')
    title = item.get('title') or item.get('name')
    overview = item.get('overview', 'No description available.')
    poster = f"https://image.tmdb.org/t/p/w500{item.get('poster_path')}"
    
    cast, director, producer = get_detailed_info(m_type, item['id'])

    caption = (
        f"🎬 *{title}*\n\n"
        f"{overview[:350]}...\n\n"
        f"👤 *Cast:* {cast}\n"
        f"🎬 *Director:* {director}\n"
        f"💼 *Producer:* {producer}\n\n"
        f"🎭 **Ads: Sponsored by [Our Channel]({CHANNEL_LINK})**\n"
        f"🚀 *Join us for more exclusive leaks and updates!*"
    )

    for user_id in get_users():
        try:
            await context.bot.send_photo(chat_id=user_id, photo=poster, caption=caption, parse_mode='Markdown')
            await asyncio.sleep(0.1) 
        except Exception as e:
            logging.warning(f"Failed to send to {user_id}: {e}")

# --- BOT HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    add_user(user_id)
    
    await update.message.reply_text("👋 Welcome! You are now subscribed. You will receive new updates every 15 minutes!")
    await send_auto_post(context)

# --- MAIN ---
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    
    # Start Health Server thread
    threading.Thread(target=run_health_server, daemon=True).start()

    # Build Application
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler('start', start))

    # Scheduler: 15 minutes = 900 seconds
    job_queue = application.job_queue
    job_queue.run_repeating(send_auto_post, interval=900, first=10)

    print("Bot is starting...")
    application.run_polling(drop_pending_updates=True)
    
