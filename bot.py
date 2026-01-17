import logging, sqlite3, asyncio, os, sys, threading, requests, random
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.constants import ParseMode
from telegram.error import Forbidden, BadRequest, InvalidToken
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler

# --- CONFIGURATION ---
TOKEN = os.getenv("BOT_TOKEN")
XMDB_API_KEY = os.getenv("XMDB_API_KEY") # Get from http://www.omdbapi.com/
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
SPONSOR_CHANNEL = os.getenv("CHANNEL_ID", "@SponsorChannel")
PORT = int(os.environ.get("PORT", 8080))
EARNINGS_PER_POST = 10 # ₹10 earned per automated post

if not TOKEN or ":" not in TOKEN:
    print("❌ FATAL: Invalid BOT_TOKEN.")
    sys.exit(1)

# --- DATABASE SETUP ---
class Database:
    def __init__(self):
        self.conn = sqlite3.connect("bot_data.db", check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.cursor.execute("""CREATE TABLE IF NOT EXISTS users 
            (user_id INTEGER PRIMARY KEY, username TEXT, join_date TEXT)""")
        self.cursor.execute("CREATE TABLE IF NOT EXISTS admin_stats (total_earned INTEGER DEFAULT 0)")
        self.cursor.execute("INSERT OR IGNORE INTO admin_stats (rowid, total_earned) VALUES (1, 0)")
        self.conn.commit()

    def add_user(self, user_id, username):
        date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.cursor.execute("INSERT OR IGNORE INTO users (user_id, username, join_date) VALUES (?, ?, ?)", (user_id, username, date))
        self.conn.commit()

db = Database()

# --- XMDB MOVIE FETCH ---
async def fetch_movie():
    """Fetches real data from OMDb."""
    titles = ["Pathaan", "Interstellar", "Stree 2", "Inception", "Pushpa", "Animal"]
    movie_name = random.choice(titles)
    url = f"http://www.omdbapi.com/?apikey={XMDB_API_KEY}&t={movie_name}&plot=short"
    try:
        res = requests.get(url).json()
        return res if res.get("Response") == "True" else None
    except: return None

# --- AUTOMATED BLOG TASK ---
async def auto_post_job(context: ContextTypes.DEFAULT_TYPE):
    data = await fetch_movie()
    if not data: return
    
    blog_text = (
        f"🎬 **XMDB UPDATE: {data.get('Title')} ({data.get('Year')})**\n\n"
        f"📝 **Plot:** {data.get('Plot')}\n\n"
        f"⭐ **Global Rating:** {data.get('imdbRating')}/10\n"
        f"💡 **Why Watch?** This is a top-rated global masterpiece trending on OTT platforms. Must watch for entertainment!\n\n"
        f"📢 **Join Sponsor:** {SPONSOR_CHANNEL}"
    )
    
    db.cursor.execute("SELECT user_id FROM users")
    users = db.cursor.fetchall()
    for (u_id,) in users:
        try:
            await context.bot.send_photo(chat_id=u_id, photo=data.get('Poster'), caption=blog_text, parse_mode=ParseMode.MARKDOWN)
        except: pass
    
    db.cursor.execute("UPDATE admin_stats SET total_earned = total_earned + ? WHERE rowid = 1", (EARNINGS_PER_POST,))
    db.conn.commit()

# --- HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db.add_user(update.effective_user.id, update.effective_user.username)
    await update.message.reply_text("👋 Welcome! OTT Movie blogs start every 5 minutes.")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    db.cursor.execute("SELECT total_earned FROM admin_stats WHERE rowid = 1")
    earned = db.cursor.fetchone()[0]
    db.cursor.execute("SELECT COUNT(*) FROM users")
    count = db.cursor.fetchone()[0]
    await update.message.reply_text(f"📊 **Admin Panel**\n\nTotal Users: {count}\nTotal Earned: ₹{earned}")

# --- MAIN ---
def main():
    threading.Thread(target=lambda: HTTPServer(("0.0.0.0", PORT), type('H',(BaseHTTPRequestHandler,),{'do_GET':lambda s:(s.send_response(200),s.end_headers(),s.wfile.write(b'OK'))})).serve_forever(), daemon=True).start()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start)); app.add_handler(CommandHandler("stats", stats))
    app.job_queue.run_repeating(auto_post_job, interval=300, first=10)
    app.run_polling()

if __name__ == "__main__":
    main()
