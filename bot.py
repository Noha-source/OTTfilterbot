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
# Satisfies Render's mandatory port scan
def run_health_server():
    class HealthHandler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Bot is active!")
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", PORT), HealthHandler) as httpd:
        httpd.serve_forever()

# --- DATABASE SETUP ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    conn.execute('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, is_banned BOOLEAN DEFAULT 0)')
    conn.commit()
    conn.close()

# --- SEARCH & TRENDING LOGIC ---
async def fetch_tmdb(endpoint, params=None):
    url = f"https://api.themoviedb.org/3/{endpoint}"
    default_params = {"api_key": TMDB_API_KEY, "language": "en-US"}
    if params:
        default_params.update(params)
    try:
        # Using asyncio-friendly request if possible, or standard requests for simplicity
        response = requests.get(url, params=default_params).json()
        return response.get('results', [])
    except Exception as e:
        logging.error(f"TMDB Error: {e}")
        return []

# --- BOT HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Welcome to OTT Hub! I'm now fully stable.\n\nUse /search <name> or /trending")

async def trending_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    results = await fetch_tmdb("trending/all/day")
    if results:
        title = results[0].get('title') or results[0].get('name')
        await update.message.reply_text(f"🔥 Trending Now: {title}")
    else:
        await update.message.reply_text("❌ Could not fetch trending content.")

async def search_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args)
    if not query:
        await update.message.reply_text("🔎 Usage: /search <movie name>")
        return
    
    results = await fetch_tmdb("search/multi", {"query": query})
    if results:
        item = results[0]
        title = item.get('title') or item.get('name')
        overview = item.get('overview', 'No description available.')
        await update.message.reply_text(f"🎬 *{title}*\n\n{overview[:300]}...", parse_mode='Markdown')
    else:
        await update.message.reply_text("❌ No results found.")

async def broadcast_task(context: ContextTypes.DEFAULT_TYPE):
    logging.info("Running scheduled broadcast...")

# --- MAIN EXECUTION ---
if __name__ == '__main__':
    init_db()
    logging.basicConfig(level=logging.INFO)
    
    # Start Health Server in background
    threading.Thread(target=run_health_server, daemon=True).start()

    # Build Application
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    
    # Add Command Handlers
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('trending', trending_handler))
    application.add_handler(CommandHandler('search', search_handler))

    # Use Native JobQueue to avoid event loop conflicts
    job_queue = application.job_queue
    job_queue.run_repeating(broadcast_task, interval=1200, first=10)

    logging.info("🤖 Bot is active and polling...")
    # drop_pending_updates prevents 'Conflict' errors on restart
    application.run_polling(drop_pending_updates=True)
    
