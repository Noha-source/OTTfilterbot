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

# --- CONFIGURATION (Render Environment Variables) ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
TMDB_API_KEY = os.getenv("TMDB_API_KEY")
PORT = int(os.getenv("PORT", "8080")) 
DB_FILE = "bot_users.db"

# --- KEEP-ALIVE HEALTH SERVER ---
def run_health_server():
    class HealthHandler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Bot is alive!")
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", PORT), HealthHandler) as httpd:
        httpd.serve_forever()

# --- DATABASE ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    conn.execute('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, is_banned BOOLEAN DEFAULT 0)')
    conn.commit()
    conn.close()

# --- CONTENT FETCHING ---
async def fetch_trending():
    url = f"https://api.themoviedb.org/3/trending/all/day?api_key={TMDB_API_KEY}"
    try:
        response = requests.get(url).json()
        return response.get('results', [])
    except Exception:
        return []

# --- AUTOMATIC BROADCAST (Native JobQueue) ---
async def auto_broadcast(context: ContextTypes.DEFAULT_TYPE):
    logging.info("Starting Auto-Broadcast...")
    # Add your message sending logic here

# --- BOT HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Welcome to OTT Hub! Bot is now stable.")

async def trending_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    results = await fetch_trending()
    if not results:
        await update.message.reply_text("❌ Could not fetch trending content.")
        return
    title = results[0].get('title') or results[0].get('name')
    await update.message.reply_text(f"🔥 Trending Now: {title}")

# --- MAIN SETUP ---
if __name__ == '__main__':
    init_db()
    logging.basicConfig(level=logging.INFO)
    
    # Start the Health Server
    threading.Thread(target=run_health_server, daemon=True).start()

    # Build the Application
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    
    # Add Handlers
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('trending', trending_handler))

    # Setup Native JobQueue (Fixes 'no running event loop' error)
    job_queue = application.job_queue
    job_queue.run_repeating(auto_broadcast, interval=1200, first=10)

    logging.info("🤖 Bot is active and polling...")
    application.run_polling(drop_pending_updates=True)
    
