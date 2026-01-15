import logging
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, CallbackQueryHandler, MessageHandler, filters

# --- CONFIGURATION ---
BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
TMDB_API_KEY = "YOUR_TMDB_API_KEY"

# Radarr (Movies) & Sonarr (Series) Config - For "Automatic Downloads"
RADARR_URL = "http://localhost:7878/api/v3"
RADARR_KEY = "YOUR_RADARR_API_KEY"
SONARR_URL = "http://localhost:8989/api/v3"
SONARR_KEY = "YOUR_SONARR_API_KEY"

# Niche Platform Mapping (Manual mapping for platforms not always on TMDB)
NICHE_PLATFORMS = {
    "ullu": "Ullu", "rabbit": "Rabbit", "moodx": "MoodX", 
    "prime play": "Prime Play", "uncut": "Uncut"
}

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# --- 1. TMDB SEARCH ENGINE ---
async def search_tmdb(query, media_type="multi"):
    """Searches TMDB for movies or series."""
    url = f"https://api.themoviedb.org/3/search/{media_type}"
    params = {"api_key": TMDB_API_KEY, "query": query}
    response = requests.get(url, params=params)
    return response.json().get('results', [])

async def get_watch_providers(media_id, media_type):
    """Finds where the content is streaming (Netflix, Hotstar, etc.)."""
    url = f"https://api.themoviedb.org/3/{media_type}/{media_id}/watch/providers"
    params = {"api_key": TMDB_API_KEY}
    response = requests.get(url, params=params)
    results = response.json().get('results', {}).get('IN', {}) # 'IN' for India region
    
    providers = []
    if 'flatrate' in results:
        providers = [p['provider_name'] for p in results['flatrate']]
    
    return providers

# --- 2. DOWNLOAD AUTOMATION (RADARR/SONARR) ---
def add_to_radarr(tmdb_id, title):
    """Sends a download request to Radarr."""
    payload = {
        "title": title,
        "tmdbId": tmdb_id,
        "qualityProfileId": 1,  # Default profile
        "rootFolderPath": "/movies/", # Your server path
        "monitored": True,
        "addOptions": {"searchForMovie": True} # Triggers auto-search/download
    }
    try:
        r = requests.post(f"{RADARR_URL}/movie", json=payload, params={"apikey": RADARR_KEY})
        return r.status_code in [200, 201]
    except Exception as e:
        logging.error(f"Radarr Error: {e}")
        return False

def add_to_sonarr(tvdb_id, title):
    """Sends a download request to Sonarr (Note: Sonarr uses TVDB IDs, requires extra lookup)."""
    # Simplified for demo. In production, you convert TMDB ID to TVDB ID first.
    return False 

# --- 3. BOT COMMAND HANDLERS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "🎬 **Advanced OTT Bot Active**\n\n"
        "I can find content across Netflix, Hotstar, Prime, etc.\n"
        "and automate downloads to your home server.\n\n"
        "**Commands:**\n"
        "/search <name> - Search for a Movie/Series\n"
        "/trending - See what's popular"
    )
    await update.message.reply_text(welcome_text, parse_mode='Markdown')

async def search_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args)
    if not query:
        await update.message.reply_text("⚠ Please type a name. Example: `/search Mirzapur`")
        return

    results = await search_tmdb(query)
    
    if not results:
        await update.message.reply_text("❌ No results found.")
        return

    # Process top 5 results
    for item in results[:5]:
        title = item.get('title') or item.get('name')
        media_type = item.get('media_type', 'movie') # movie or tv
        tmdb_id = item.get('id')
        overview = item.get('overview', 'No description.')[:150] + "..."
        poster_path = item.get('poster_path')
        
        # Get streaming info
        providers = await get_watch_providers(tmdb_id, media_type)
        provider_text = " | ".join(providers) if providers else "Not streaming on major apps"
        
        caption = (
            f"🎥 *{title}* ({media_type.upper()})\n"
            f"⭐ Rating: {item.get('vote_average')}\n"
            f"📺 *Stream:* {provider_text}\n\n"
            f"📝 {overview}"
        )

        # Buttons
        keyboard = [
            [InlineKeyboardButton("⬇ Add to Download Queue", callback_data=f"dl_{media_type}_{tmdb_id}_{title}")]
        ]
        
        if poster_path:
            img_url = f"https://image.tmdb.org/t/p/w500{poster_path}"
            await update.message.reply_photo(photo=img_url, caption=caption, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await update.message.reply_text(caption, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data.split("_") # dl_movie_12345_Title
    action = data[0]
    media_type = data[1]
    tmdb_id = data[2]
    title = data[3]

    if action == "dl":
        if media_type == "movie":
            success = add_to_radarr(tmdb_id, title)
            if success:
                await query.edit_message_caption(caption=f"✅ *{title}* added to Radarr. Downloading started!", parse_mode='Markdown')
            else:
                await query.edit_message_caption(caption=f"❌ Failed to add *{title}* to Radarr. Check server logs.", parse_mode='Markdown')
        elif media_type == "tv":
            await query.edit_message_caption(caption="⚠ Auto-download for Series (Sonarr) requires TVDB ID conversion (Advanced Logic).", parse_mode='Markdown')

# --- MAIN EXECUTION ---
if __name__ == '__main__':
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('search', search_handler))
    application.add_handler(CallbackQueryHandler(button_callback))
    
    print("Bot is running...")
    application.run_polling()
