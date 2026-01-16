import logging
import sqlite3
import requests
import asyncio
import os
import threading
import http.server
import socketserver
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler

# --- CONFIGURATION ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
TMDB_API_KEY = os.getenv("TMDB_API_KEY")
PORT = int(os.getenv("PORT", "8080")) 
DB_FILE = "bot_users.db"
# Replace with your actual channel link
CHANNEL_LINK = "https://t.me/YourChannelUsername" 

# --- KEEP-ALIVE HEALTH SERVER ---
def run_health_server():
    class HealthHandler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Bot Active")
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", PORT), HealthHandler) as httpd:
        httpd.serve_forever()

# --- DATABASE ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    conn.execute('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY)')
    conn.commit()
    conn.close()

def get_users():
    conn = sqlite3.connect(DB_FILE)
    users = [row[0] for row in conn.execute('SELECT user_id FROM users').fetchall()]
    conn.close()
    return users

# --- ADVANCED TMDB FETCHING ---
def get_detailed_info(media_type, item_id):
    url = f"https://api.themoviedb.org/3/{media_type}/{item_id}?api_key={TMDB_API_KEY}&append_to_response=credits"
    try:
        data = requests.get(url).json()
        credits = data.get('credits', {})
        cast = ", ".join([m['name'] for m in credits.get('cast', [])[:3]])
        director = ", ".join([m['name'] for m in credits.get('crew', []) if m['job'] == 'Director'])
        producer = ", ".join([m['name'] for m in credits.get('crew', []) if m['job'] == 'Producer'][:1])
        return cast, director, producer
    except:
        return "N/A", "N/A", "N/A"

# --- AUTOMATIC POST GENERATOR ---
async def send_auto_post(context: ContextTypes.DEFAULT_TYPE):
    # Fetch trending content to post
    url = f"https://api.themoviedb.org/3/trending/all/day?api_key={TMDB_API_KEY}"
    results = requests.get(url).json().get('results', [])
    if not results: return

    import random
    item = random.choice(results[:10]) # Pick a random trending item
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
        f"✨ *Backstage Gossip:* The production team faced intense challenges filming in remote locations, "
        f"but the chemistry between the leads kept the energy high every single day!\n\n"
        f"🎭 **Ads: Sponsored by [Our Telegram Channel]({CHANNEL_LINK})**\n"
        f"🚀 *Join us for more exclusive leaks and updates!*"
    )

    for user_id in get_users():
        try:
            await context.bot.send_photo(chat_id=user_id, photo=poster, caption=caption, parse_mode='Markdown')
            await asyncio.sleep(0.1) # Prevent flood
        except: pass

# --- BOT HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = sqlite3.connect(DB_FILE)
    conn.execute('INSERT OR IGNORE INTO users (user_id) VALUES (?)', (user_id,))
    conn.commit()
    conn.close()
    
    await update.message.reply_text("👋 Welcome! You are now subscribed. You will receive new updates every 15 minutes!")
    # Trigger immediate post upon start
    await send_auto_post(context)

# --- MAIN ---
if __name__ == '__main__':
    init_db()
    logging.basicConfig(level=logging.INFO)
    threading.Thread(target=run_health_server, daemon=True).start()

    application = ApplicationBuilder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler('start', start))

    # Scheduler: 15 minutes = 900 seconds
    job_queue = application.job_queue
    job_queue.run_repeating(send_auto_post, interval=900, first=10)

    application.run_polling(drop_pending_updates=True)
