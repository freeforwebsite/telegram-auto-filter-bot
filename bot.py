import os
import json
import re
import uuid
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, MessageHandler, CommandHandler, CallbackQueryHandler, filters, ContextTypes

def load_env():
    try:
        with open('.env', 'r') as f:
            for line in f:
                if line.strip() and not line.startswith('#'):
                    key, val = line.strip().split('=', 1)
                    os.environ[key] = val
    except FileNotFoundError:
        pass

load_env()

import sys

BOT_CONFIGS = {
    "1": {
        "name": "CinePrime Auto Filter",
        "token": "8861631170:AAEBV-3N2KzDRy1axQiHT_xa_8totMEipTk",
        "channel_id": -1003217836347,
        "db_name": "telegram_bot",
        "mongo_uri": "mongodb+srv://dharani2006lakshmi_db_user:Byi5WDiKV6H53Xe1@cluster0.p93dbly.mongodb.net",
        "alt_db_name": "autofilter_bot2",
        "alt_mongo_uri": "mongodb+srv://firee4531_db_user:firee_2006@cluster0.n2iizcz.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0",
        "port": 8081
    },
    "2": {
        "name": "CinePrime Auto Filter 2",
        "token": "8918387267:AAG3Ht0eoWPYgkE6NHrxSr1X93b2FQAPfA0",
        "channel_id": -1004495752619,
        "db_name": "autofilter_bot2",
        "mongo_uri": "mongodb+srv://firee4531_db_user:firee_2006@cluster0.n2iizcz.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0",
        "alt_db_name": "telegram_bot",
        "alt_mongo_uri": "mongodb+srv://dharani2006lakshmi_db_user:Byi5WDiKV6H53Xe1@cluster0.p93dbly.mongodb.net",
        "port": 8082
    }
}

# Determine instance from CLI argument (e.g. 'python bot.py 1') or environment variable
instance_key = "1"
if len(sys.argv) > 1 and sys.argv[1] in ["1", "2"]:
    instance_key = sys.argv[1]
elif os.environ.get("BOT_INSTANCE") in ["1", "2"]:
    instance_key = os.environ.get("BOT_INSTANCE")
elif os.environ.get("INSTANCE") in ["1", "2"]:
    instance_key = os.environ.get("INSTANCE")

curr_cfg = BOT_CONFIGS.get(instance_key, BOT_CONFIGS["1"])

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") or curr_cfg["token"]
DATABASE_CHANNEL_ID = int(os.environ.get("DATABASE_CHANNEL_ID") or curr_cfg["channel_id"])
DATABASE_NAME = os.environ.get("DATABASE_NAME") or curr_cfg["db_name"]
PORT = int(os.environ.get("PORT") or curr_cfg["port"])
os.environ["PORT"] = str(PORT)

print(f"🤖 [AUTOFILTER] Starting {curr_cfg['name']} (Instance {instance_key})")
print(f"📁 [AUTOFILTER] Channel ID: {DATABASE_CHANNEL_ID}")
print(f"🗄️ [AUTOFILTER] Primary Database: {DATABASE_NAME}")

import pymongo

MONGODB_URI = os.environ.get("MONGODB_URI") or curr_cfg.get("mongo_uri") or os.environ.get("MONGO_URI") or ""
ALT_MONGODB_URI = curr_cfg.get("alt_mongo_uri") or os.environ.get("LEGACY_170K_DB_URI") or ""
ALT_DATABASE_NAME = curr_cfg.get("alt_db_name")

client = None
db = None
movies_collection = None
users_collection = None
filters_collection = None
config_collection = None
alt_client = None
alt_movies_collection = None

if MONGODB_URI:
    try:
        client = pymongo.MongoClient(MONGODB_URI)
        db = client[DATABASE_NAME]
        movies_collection = db['movies']
        users_collection = db['users']
        filters_collection = db['custom_filters']
        config_collection = db['config']
        
        # Connect to Cinescraper's database
        scrape_db = client['cinesearch_db']
        scrape_queue = scrape_db['scrape_queue']
        print(f"✅ Connected to Primary MongoDB database '{DATABASE_NAME}' successfully!")
    except Exception as e:
        print(f"MongoDB Primary Connection Error: {e}")

if ALT_MONGODB_URI and ALT_DATABASE_NAME:
    try:
        alt_client = pymongo.MongoClient(ALT_MONGODB_URI)
        alt_movies_collection = alt_client[ALT_DATABASE_NAME]['movies']
        print(f"✅ Connected to Secondary MongoDB database '{ALT_DATABASE_NAME}' for full catalog fallback!")
    except Exception as e:
        print(f"MongoDB Secondary Connection Notice: {e}")

# Shared Search Coordination Collection
shared_coord_col = None
try:
    c_client = alt_client if instance_key == "1" else client
    if c_client is not None:
        shared_coord_col = c_client['cineprime_community']['search_coordination']
except Exception:
    pass

def track_user(user):
    if users_collection is not None and user is not None:
        try:
            users_collection.update_one(
                {'user_id': user.id},
                {'$set': {
                    'username': user.username,
                    'first_name': user.first_name,
                    'last_name': user.last_name
                }},
                upsert=True
            )
        except Exception as e:
            print(f"Error tracking user: {e}")


ADMIN_IDS = [int(x.strip()) for x in os.environ.get("ADMINS", "").split(",") if x.strip().isdigit()]

def admin_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        is_authorized = False
        
        if user_id in ADMIN_IDS:
            is_authorized = True
        elif db is not None:
            config = db['config'].find_one({'type': 'bot_admins'})
            if config and config.get('admins') and user_id in config['admins']:
                is_authorized = True
                
        if not is_authorized:
            return
            
        return await func(update, context)
    return wrapper

async def claim_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if db is None:
        await update.message.reply_text("Database not connected!")
        return
        
    config = db['config'].find_one({'type': 'bot_admins'})
    if config and config.get('admins'):
        await update.message.reply_text("⛔ **Owner is already set!**", parse_mode="Markdown")
        return
        
    db['config'].update_one(
        {'type': 'bot_admins'}, 
        {'$set': {'admins': [update.effective_user.id]}}, 
        upsert=True
    )
    await update.message.reply_text("✅ **Success!** You are now the bot owner. You can use /users and other admin commands.", parse_mode="Markdown")


async def whereami_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import platform, socket, os
    
    info = []
    info.append(f"**Hostname:** `{socket.gethostname()}`")
    info.append(f"**System:** `{platform.system()} {platform.release()}`")
    
    # Check common hosting env vars
    if os.environ.get('RENDER'):
        info.append("☁️ **Host:** Render.com")
        info.append(f"📦 **Service Name:** `{os.environ.get('RENDER_SERVICE_NAME', 'Unknown')}`")
    elif os.environ.get('SPACE_ID'):
        info.append("☁️ **Host:** HuggingFace Spaces")
        info.append(f"📦 **Space:** `{os.environ.get('SPACE_ID')}`")
    elif os.environ.get('DYNO'):
        info.append("☁️ **Host:** Heroku")
    elif os.environ.get('KOYEB_APP_NAME'):
        info.append("☁️ **Host:** Koyeb")
    else:
        info.append("☁️ **Host:** Unknown / Local")
        
    await update.message.reply_text("\n".join(info), parse_mode="Markdown")

def add_movie(file_id, file_name, caption, source_chat_id=None, source_message_id=None, file_size=None):
    if movies_collection is None:
        print("WARNING: MongoDB not connected. Cannot add movie.")
        return False
        
    # Check if file already exists
    existing_movie = movies_collection.find_one({'file_id': file_id})
    if existing_movie:
        if not existing_movie.get('file_size') and file_size:
            movies_collection.update_one({'_id': existing_movie['_id']}, {'$set': {'file_size': file_size}})
            return True
        return False
        
    movie = {
        'id': str(uuid.uuid4()),
        'file_id': file_id,
        'file_name': file_name,
        'caption': caption,
        'source_chat_id': source_chat_id,
        'source_message_id': source_message_id,
        'file_size': file_size
    }
    movies_collection.insert_one(movie)
    return True

import re
import urllib.parse
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def get_watch_keyboard(movie):
    render_url = os.environ.get('RENDER_EXTERNAL_URL', 'https://t.me/cinevalut')
    
    # If the URL is just the telegram channel (local mode), don't build a complex path
    if render_url == 'https://t.me/cinevalut':
        watch_url = render_url
    else:
        watch_url = f"{render_url}/v/{movie.get('id') or str(movie.get('_id', ''))}"
        
    return InlineKeyboardMarkup([[InlineKeyboardButton("▶️ Watch Online", url=watch_url)]])

def normalize_text(text):
    text = text.lower()
    # Normalize season: s05, season 5, s5 -> s5
    text = re.sub(r'\b(?:s|season\s*)0*(\d+)', r's\1', text)
    # Normalize episode: e08, ep08, episode 8 -> ep8
    text = re.sub(r'\b(?:e|ep|episode\s*)0*(\d+)', r'ep\1', text)
    # Replace special characters with spaces
    text = re.sub(r'[^a-z0-9\s]', ' ', text)
    return text

def search_movies(query):
    if movies_collection is None and alt_movies_collection is None:
        return []
        
    # Extract alphanumeric words from the query
    words = re.findall(r'[a-zA-Z0-9]+', query)
    if not words:
        return []
        
    # Create regex conditions for words (using re.compile for exact BSON matching)
    conditions = [{"file_name": re.compile(re.escape(word), re.IGNORECASE)} for word in words]
    combined = []
    seen_ids = set()
    seen_signatures = set()

    # 1. Search Primary Database
    if movies_collection is not None:
        try:
            cursor = movies_collection.find({"$and": conditions}).limit(50)
            for r in cursor:
                fid = r.get('file_id')
                fn = (r.get('file_name') or '').strip().lower()
                fsz = r.get('file_size') or 0
                sig = (fn, fsz)
                if fid and fid not in seen_ids and sig not in seen_signatures:
                    seen_ids.add(fid)
                    seen_signatures.add(sig)
                    combined.append(r)
        except Exception as e:
            print(f"Primary MongoDB Search Error: {e}")

    # 2. Enrich from Secondary Database if needed
    if alt_movies_collection is not None and len(combined) < 30:
        try:
            alt_cursor = alt_movies_collection.find({"$and": conditions}).limit(30)
            for r in alt_cursor:
                fid = r.get('file_id')
                fn = (r.get('file_name') or '').strip().lower()
                fsz = r.get('file_size') or 0
                sig = (fn, fsz)
                if fid and fid not in seen_ids and sig not in seen_signatures:
                    seen_ids.add(fid)
                    seen_signatures.add(sig)
                    combined.append(r)
        except Exception as e:
            print(f"Secondary MongoDB Search Error: {e}")

    return combined

def get_movie_by_id(movie_id):
    from bson.objectid import ObjectId
    for col in [movies_collection, alt_movies_collection]:
        if col is None:
            continue
        try:
            try:
                obj_id = ObjectId(movie_id)
                m = col.find_one({'$or': [{'id': movie_id}, {'_id': obj_id}]})
            except Exception:
                m = col.find_one({'id': movie_id})
            if m:
                return m
        except Exception:
            pass
    return None

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    track_user(update.effective_user)
    if update.effective_chat.type == 'private':
        # Check for deep link request: /start get_uuid
        text = update.message.text
        if len(text.split()) > 1:
            arg = text.split()[1]
            if arg.startswith("get_"):
                movie_id = arg[4:]
                movie = get_movie_by_id(movie_id)
                if movie:
                    if movie.get("poster_url"):
                        caption = f"🎬 **{movie.get('title', 'Unknown')}**\n\n"
                        caption += f"⭐ **Rating:** {movie.get('rating', 'N/A')}/10\n"
                        caption += f"📅 **Release Date:** {movie.get('release_date', 'N/A')}\n\n"
                        caption += f"📖 **Plot:** {str(movie.get('overview', 'No plot available.'))[:500]}..."
                        try:
                            await context.bot.send_photo(
                                chat_id=update.effective_chat.id,
                                photo=movie["poster_url"],
                                caption=caption,
                                parse_mode="Markdown"
                            )
                        except Exception as e:
                            print(f"Failed to send poster: {e}")
                            
                    try:
                        await context.bot.copy_message(
                            chat_id=update.effective_chat.id,
                            from_chat_id=movie.get('source_chat_id'),
                            message_id=movie.get('source_message_id'),
                            reply_markup=get_watch_keyboard(movie)
                        )
                    except Exception as e:
                        try:
                            await context.bot.send_document(
                                chat_id=update.effective_chat.id,
                                document=movie.get('file_id'),
                                caption=movie.get('caption', ''),
                                parse_mode='HTML',
                                reply_markup=get_watch_keyboard(movie)
                            )
                        except Exception as ex:
                            await update.message.reply_text(f"🚨 **Error Sending File:**\n`{ex}`", parse_mode="Markdown")
                else:
                    await update.message.reply_text("🚨 **Error:** This movie was not found in the database. It may have been deleted.")
                return

        await update.message.reply_text(
            "🤖 **Auto Filter Bot is Online!**\n\n"
            "**How to use:**\n"
            "1. Send or forward any movie file to me here in private to add it to my database.\n"
            "2. Add me to a Group Chat as an Admin.\n"
            "3. When anyone types a movie name in the group, I will reply with a download button!",
            parse_mode="Markdown"
        )

async def index_movie_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != 'private':
        return
        
    msg = update.message
    if not msg.document and not msg.video:
        await msg.reply_text("⚠️ Please send a Video or Document file.")
        return
        
    file = msg.document or msg.video
    file_id = file.file_id
    file_name = file.file_name or "Unknown_Movie"
    caption = msg.caption_html if msg.caption else ""
    
    # Forward a backup of the file to the Database Channel if not already there
    if update.effective_chat.id != DATABASE_CHANNEL_ID:
        try:
            forwarded_msg = await context.bot.copy_message(
                chat_id=DATABASE_CHANNEL_ID,
                from_chat_id=msg.chat.id,
                message_id=msg.message_id
            )
            channel_message_id = forwarded_msg.message_id
            channel_chat_id = DATABASE_CHANNEL_ID
        except Exception as e:
            print(f"Failed to backup to Database Channel: {e}")
            channel_message_id = msg.message_id
            channel_chat_id = msg.chat.id
    else:
        channel_message_id = msg.message_id
        channel_chat_id = msg.chat.id
        
    success = add_movie(file_id, file_name, caption, channel_chat_id, channel_message_id, file.file_size)
    if success:
        await msg.reply_text(f"✅ **Saved to Database!**\n\nName: `{file_name}`\n\n**File ID** (Click to copy): `{file_id}`", parse_mode="Markdown")
    else:
        # Even if it's already in the DB, give them the file_id so they can still use it!
        await msg.reply_text(f"⚠️ This file is already in the database.\n\n**File ID** (Click to copy): `{file_id}`", parse_mode="Markdown")

BOT_USERNAME = None

async def post_init(application: Application):
    global BOT_USERNAME
    BOT_USERNAME = application.bot.username
    print(f"Bot Username: {BOT_USERNAME}")
    
    # Start the optional aiohttp Streaming Server inside PTB's asyncio loop if configured
    try:
        from stream_server.server import start_stream_server
        import asyncio
        asyncio.create_task(start_stream_server())
    except Exception as e:
        print(f"Notice: Web stream server skipped: {e}")

_LANG_NAMES = ['Tamil', 'Telugu', 'Hindi', 'Malayalam', 'Kannada', 'English', 'Bengali', 'Marathi', 'Punjabi', 'Multi', 'Dual']
_LANG_MAP = {l.lower(): l for l in _LANG_NAMES}
_LANG_MAP.update({'tam': 'Tamil', 'tel': 'Telugu', 'hin': 'Hindi', 'mal': 'Malayalam', 'kan': 'Kannada', 'eng': 'English'})
_TLD_REGEX = r'(?i)^(?:https?://)?(?:www\.)?[a-z0-9-]+\.(?:com|net|org|in|vip|solar|is|wf|pm|to|cc|me|live|xyz|site|club|app|tv|link|world|pro|co)\s*[-–_:]*\s*'

def format_button_label(movie, fallback_query=""):
    raw_name = movie.get('file_name', '') or ''
    caption = movie.get('caption', '') or ''
    size_bytes = movie.get('file_size') or movie.get('size') or 0
    full_text = f"{raw_name} {caption}"

    # 1. Size
    sz_str = ""
    if size_bytes:
        try:
            sb = float(size_bytes)
            if sb >= 1024**3:
                val = sb / (1024**3)
                sz_str = f"{val:.2f} GB"
            elif sb >= 1024**2:
                sz_str = f"{int(round(sb / (1024**2)))} MB"
            elif sb >= 1024:
                sz_str = f"{int(round(sb / 1024))} KB"
        except Exception:
            pass

    if not sz_str:
        sz_m = re.search(r'\b(\d+(?:\.\d+)?\s*(?:GB|MB))\b', full_text, re.IGNORECASE)
        if sz_m:
            sz_str = sz_m.group(1).upper()
        else:
            sz_str = "N/A"

    # Clean name
    t = re.sub(r'@[a-zA-Z0-9_]+', '', raw_name)
    t = re.sub(r'\.(mkv|mp4|avi|webm|ts|mov)$', '', t, flags=re.IGNORECASE)
    t = re.sub(_TLD_REGEX, '', t.strip())

    # Extract language
    found_langs = []
    for l_key, l_val in _LANG_MAP.items():
        if re.search(r'\b' + l_key + r'\b', full_text, re.IGNORECASE):
            if l_val not in found_langs:
                found_langs.append(l_val)
    lang_str = " ".join(found_langs[:2]) if found_langs else ""

    # Extract Quality
    quality = ""
    res_m = re.search(r'\b(2160p|4k|1080p|720p|540p|480p|360p)\b', full_text, re.IGNORECASE)
    if res_m:
        quality = res_m.group(1).upper() if res_m.group(1).lower() == '4k' else res_m.group(1).lower()
    else:
        rip_m = re.search(r'\b(web-dl|webrip|hdrip|bluray|hdtv|dvdrip|cam)\b', full_text, re.IGNORECASE)
        if rip_m:
            q_raw = rip_m.group(1).lower()
            quality = {'web-dl': 'WEB-DL', 'webrip': 'WEBRip', 'hdrip': 'HDRip', 'bluray': 'BluRay', 'hdtv': 'HDTV'}.get(q_raw, q_raw.upper())

    # Series vs Movie
    series_m = re.search(r'\b(s\d{1,2}(?:[\s._-]*e\d{1,2})?|season\s*\d+)\b', t, re.IGNORECASE)
    year_m = re.search(r'\b(19\d\d|20\d\d)\b', t)

    movie_title = ""
    if series_m:
        title_part = t[:series_m.start()]
        season_part = series_m.group(0).upper().replace(' ', '')
        clean_title = re.sub(r'[._-]+', ' ', title_part).strip(' ._-([{}])')
        clean_title = re.sub(r'\s+', ' ', clean_title)
        movie_title = f"{clean_title} {season_part}".strip()
    elif year_m:
        title_part = t[:year_m.start()]
        year_str = year_m.group(1)
        clean_title = re.sub(r'[._-]+', ' ', title_part).strip(' ._-([{}])')
        clean_title = re.sub(r'\s+', ' ', clean_title)
        if not clean_title:
            clean_title = fallback_query.title() if fallback_query else "Movie"
        movie_title = f"{clean_title} ({year_str})"
    else:
        stop_tokens = list(_LANG_MAP.keys()) + ['1080p', '720p', '480p', 'hdrip', 'web-dl', 'webrip', 'bluray', 'x264', 'x265', 'hevc']
        pattern = r'\b(' + '|'.join(re.escape(tok) for tok in stop_tokens) + r')\b'
        match = re.search(pattern, t, re.IGNORECASE)
        if match:
            clean_title = t[:match.start()]
        else:
            clean_title = t
        clean_title = re.sub(r'[._-]+', ' ', clean_title).strip(' ._-([{}])')
        clean_title = re.sub(r'\s+', ' ', clean_title)
        movie_title = clean_title or (fallback_query.title() if fallback_query else "Movie")

    # Title-case clean title if it's all lower
    if movie_title.islower():
        movie_title = movie_title.title()

    # Cap movie title so button fits comfortably on Telegram clients
    if len(movie_title) > 28:
        movie_title = movie_title[:26].rstrip() + ".."

    parts = [sz_str, movie_title]
    meta = f"{lang_str} {quality}".strip()
    if meta:
        parts.append(meta)

    return " | ".join(parts)

def build_paginated_keyboard(results, page, query):
    ITEMS_PER_PAGE = 10
    total_results = len(results)
    total_pages = (total_results + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    
    start_idx = (page - 1) * ITEMS_PER_PAGE
    end_idx = start_idx + ITEMS_PER_PAGE
    
    page_results = results[start_idx:end_idx]
    
    keyboard = []
    
    # Fake Filter Buttons (Aesthetic)
    keyboard.append([
        InlineKeyboardButton("Quality", callback_data=f"menu_quality_{query}"),
        InlineKeyboardButton("Language", callback_data=f"menu_language_{query}"),
        InlineKeyboardButton("Season", callback_data=f"menu_season_{query}")
    ])
    keyboard.append([InlineKeyboardButton("⬆️ SELECT OPTION HERE ⬆️", callback_data="ignore")])
    
    for movie in page_results:
        btn_label = format_button_label(movie, fallback_query=query)
        
        # Use deep linking to redirect to bot PM
        if BOT_USERNAME:
            url = f"https://t.me/{BOT_USERNAME}?start=get_{movie.get('id') or str(movie['_id'])}"
            keyboard.append([InlineKeyboardButton(btn_label, url=url)])
        else:
            keyboard.append([InlineKeyboardButton(btn_label, callback_data=f"get_{movie.get('id') or str(movie['_id'])}")])
        
    # Pagination Footer
    if total_pages > 1:
        nav_row = []
        if page > 1:
            nav_row.append(InlineKeyboardButton("PAGE", callback_data=f"page_{page-1}_{query}"))
        else:
            nav_row.append(InlineKeyboardButton("PAGE", callback_data="ignore"))
            
        nav_row.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="ignore"))
        
        if page < total_pages:
            nav_row.append(InlineKeyboardButton("NEXT ⏩", callback_data=f"page_{page+1}_{query}"))
        else:
            nav_row.append(InlineKeyboardButton("NEXT ⏩", callback_data="ignore"))
            
        keyboard.append(nav_row)
        
    return InlineKeyboardMarkup(keyboard)

def build_quality_menu(query):
    qualities = ["360p", "480p", "720p", "1080p", "1440p", "2160p"]
    keyboard = [[InlineKeyboardButton("⇊ SELECT QUALITY ⇊", callback_data="ignore")]]
    for q in qualities:
        keyboard.append([InlineKeyboardButton(q, callback_data=f"apply_{q}_{query}")])
    keyboard.append([InlineKeyboardButton("🔙 BACK TO FILES 🔙", callback_data=f"page_1_{query}")])
    return InlineKeyboardMarkup(keyboard)

def build_language_menu(query):
    languages = ["Tamil", "Malayalam", "English", "Hindi", "Telugu", "Kannada", "Gujarati", "Marathi", "Punjabi"]
    keyboard = [[InlineKeyboardButton("⇊ SELECT LANGUAGE ⇊", callback_data="ignore")]]
    for lang in languages:
        keyboard.append([InlineKeyboardButton(lang, callback_data=f"apply_{lang}_{query}")])
    keyboard.append([InlineKeyboardButton("🔙 BACK TO FILES 🔙", callback_data=f"page_1_{query}")])
    return InlineKeyboardMarkup(keyboard)

def build_season_menu(query):
    keyboard = [[InlineKeyboardButton("⇊ SELECT SEASON ⇊", callback_data="ignore")]]
    for i in range(1, 11, 2):
        s1 = f"s0{i}" if i < 10 else f"s{i}"
        s2 = f"s0{i+1}" if i+1 < 10 else f"s{i+1}"
        row = [
            InlineKeyboardButton(f"Season {i}", callback_data=f"apply_{s1}_{query}"),
            InlineKeyboardButton(f"Season {i+1}", callback_data=f"apply_{s2}_{query}")
        ]
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("🔙 BACK TO FILES 🔙", callback_data=f"page_1_{query}")])
    return InlineKeyboardMarkup(keyboard)

import urllib.parse

async def delete_after(message, seconds):
    await asyncio.sleep(seconds)
    try:
        await message.delete()
    except Exception:
        pass

CONVERSATIONAL_WORDS = {
    "hi", "hello", "hey", "bro", "bhai", "admin", "admins", "please", "plz", "pls",
    "thanks", "thank", "thx", "tq", "ok", "okay", "yes", "no", "how", "what",
    "where", "why", "who", "when", "which", "can", "could", "would", "is", "are",
    "am", "was", "were", "do", "does", "did", "have", "has", "had", "only",
    "available", "rules", "rule", "welcome", "good", "morning", "night", "super",
    "nice", "awesome", "lol", "wait", "done", "help", "need", "give", "send",
    "link", "channel", "group", "bot", "movie", "movies", "check", "sir", "ott",
    "here", "there", "anyone", "someone", "tell", "say", "know", "new", "all",
    "post", "upload", "update", "working", "problem", "issue", "chat", "msg",
    "download", "links", "linke"
}

def is_conversational_text(text: str) -> bool:
    """Detects whether text is casual conversational chat rather than a movie title query."""
    if not text:
        return True
    cleaned = re.sub(r'[^a-zA-Z0-9\s]', ' ', text).lower().strip()
    words = cleaned.split()
    if not words:
        return True
    
    # Single conversational word (e.g. "hi", "ok", "hello", "rules", "only")
    if len(words) == 1 and words[0] in CONVERSATIONAL_WORDS:
        return True
    
    # First word starts with question words or greeting words
    if words[0] in {"how", "what", "where", "why", "who", "when", "which", "can", "could", "would", "is", "are", "do", "does", "did", "hi", "hello", "hey", "please", "plz", "only", "will"}:
        return True
        
    # High proportion of conversational words or conversational sentence
    match_count = sum(1 for w in words if w in CONVERSATIONAL_WORDS)
    if len(words) >= 5 and match_count >= 1:
        return True
    if len(words) > 2 and (match_count / len(words)) >= 0.33:
        return True
        
    return False

async def execute_movie_search(update: Update, context: ContextTypes.DEFAULT_TYPE, query: str, is_explicit_command: bool = False):
    is_group = (update.effective_chat.type != 'private')
    msg_id = update.message.message_id
    chat_id = update.effective_chat.id
    coord_key = f"{chat_id}_{msg_id}"

    import time
    start_time = time.time()

    # =========================================================================
    # MULTI-BOT GROUP SEARCH COORDINATION
    # 1st Preference: Instance 2 (New AutoFilter Bot - Storage Channels DB)
    # 2nd Preference: Instance 1 (170k File Bot - Legacy DB Fallback)
    # =========================================================================
    if is_group:
        if instance_key == "2":
            # 1st Preference: New AutoFilter Bot
            if shared_coord_col is not None:
                try:
                    shared_coord_col.update_one(
                        {"_id": coord_key},
                        {"$set": {"status": "searching", "by": "bot_2", "start_time": time.time()}},
                        upsert=True
                    )
                except Exception:
                    pass

            results = search_movies(query)

            if not results:
                if shared_coord_col is not None:
                    try:
                        shared_coord_col.update_one(
                            {"_id": coord_key},
                            {"$set": {"status": "no_results", "by": "bot_2", "done_time": time.time()}},
                            upsert=True
                        )
                    except Exception:
                        pass
                if not is_explicit_command:
                    return  # Stay completely silent in group on passive messages
            else:
                if shared_coord_col is not None:
                    try:
                        shared_coord_col.update_one(
                            {"_id": coord_key},
                            {"$set": {"status": "handled", "by": "bot_2", "count": len(results), "done_time": time.time()}},
                            upsert=True
                        )
                    except Exception:
                        pass

        elif instance_key == "1":
            # 2nd Preference: 170k Legacy Bot
            for _ in range(18):  # 18 * 0.25s = 4.5s max
                await asyncio.sleep(0.25)
                if shared_coord_col is not None:
                    try:
                        entry = shared_coord_col.find_one({"_id": coord_key})
                        if entry:
                            st = entry.get("status")
                            if st == "handled" or entry.get("handled"):
                                return
                            elif st == "no_results":
                                break
                    except Exception:
                        pass

            results = search_movies(query)
            if not results:
                if not is_explicit_command:
                    return  # Silent if no results on passive text
            else:
                if shared_coord_col is not None:
                    try:
                        entry = shared_coord_col.find_one({"_id": coord_key})
                        if entry and (entry.get("status") == "handled" or entry.get("handled")):
                            return
                        shared_coord_col.update_one(
                            {"_id": coord_key},
                            {"$set": {"status": "handled", "by": "bot_1", "count": len(results), "done_time": time.time()}},
                            upsert=True
                        )
                    except Exception:
                        pass
        else:
            results = search_movies(query)
            if not results and not is_explicit_command:
                return
    else:
        # In Private Messages: Always search directly
        results = search_movies(query)

    end_time = time.time()
    search_time = round(end_time - start_time, 3)

    if not results:
        # In groups on passive messages: stay completely silent!
        if is_group and not is_explicit_command:
            return

        # If user explicitly used command in group, notify cleanly
        if is_group and is_explicit_command:
            clean_q = query.strip()
            not_found_group = (
                f"❌ **Movie Not Found!**\n\n"
                f"No files found matching: `{clean_q}`\n\n"
                f"💡 *You can request it using `/request {clean_q}`!*"
            )
            sent = await update.message.reply_text(not_found_group, parse_mode="Markdown")
            asyncio.create_task(delete_after(sent, 60))
            return

        # In private chat only: send not found guide & queue to scraper
        try:
            if scrape_queue is not None:
                import datetime
                clean_query = query.strip()
                scrape_queue.update_one(
                    {"movie_name": {"$regex": f"^{re.escape(clean_query)}$", "$options": "i"}},
                    {
                        "$setOnInsert": {
                            "movie_name": clean_query, 
                            "status": "pending",
                            "is_urgent": True,
                            "added_on": datetime.datetime.utcnow()
                        },
                        "$addToSet": {"requested_by": update.effective_chat.id}
                    },
                    upsert=True
                )
        except Exception as e:
            print(f"Failed to auto-queue {query}: {e}")

        not_found_text = (
            f"❌ **Movie Not Found!**\n\n"
            f"I couldn't find anything matching: `{query}`\n\n"
            "🤖 **Wait! I have automatically requested our AI Scraper to find this for you!**\n"
            "Please wait a few hours and try searching again!"
        )
        google_url = f"https://www.google.com/search?q={urllib.parse.quote(query)}"
        keyboard = [[InlineKeyboardButton("🔍 DO GOOGLE", url=google_url)]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(not_found_text, reply_markup=reply_markup, parse_mode="Markdown")
        return

    short_query = query[:40]
    reply_markup = build_paginated_keyboard(results, 1, short_query)

    user_name = update.effective_user.first_name if update.effective_user else "Member"
    if update.effective_user and update.effective_user.last_name:
        user_name += f" {update.effective_user.last_name}"

    text_content = (
        f"🧿 **ᴛɪᴛʟᴇ :** `{query}`\n"
        f"📂 **ᴛᴏᴛᴀʟ ꜰɪʟᴇꜱ :** {len(results)}\n"
        f"👤 **ʀᴇǫᴜᴇꜱᴛᴇᴅ ʙʏ :** {user_name}\n"
        f"⏱ **ʀᴇꜱᴜʟᴛ ɪɴ :** {search_time} ꜱᴇᴄᴏɴᴅꜱ\n\n"
        f"👇 **𝑹𝒆𝒒𝒖𝒆𝒔𝒕𝒆𝒅 𝑭𝒊𝒍𝒆𝒔 𝑩𝒆𝒍𝒐𝒘** 👇"
    )

    sent_msg = await update.message.reply_text(
        text_content,
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

    if update.effective_chat.type != 'private':
        # Try to send a permanent copy to the user's PM
        try:
            await context.bot.send_message(
                chat_id=update.effective_user.id,
                text=text_content + "\n\n*(This is your permanent copy, it will not be deleted!)*",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
        except Exception:
            pass

        # Auto-delete BOTH the user's message and bot's message after 300s (5 mins) in group
        asyncio.create_task(delete_after(update.message, 300))
        asyncio.create_task(delete_after(sent_msg, 300))

async def movie_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Dedicated search command: /find <movie> or /movie <movie> or /search <movie>
    """
    if update.effective_user and update.effective_user.is_bot:
        return
    if update.message.sender_chat:
        return

    track_user(update.effective_user)

    query = ""
    if context.args:
        query = " ".join(context.args).strip()
    elif update.message.text:
        parts = update.message.text.split(None, 1)
        if len(parts) > 1:
            query = parts[1].strip()

    if not query:
        msg = await update.message.reply_text(
            "🎬 **Movie Search Command:**\n\n"
            "Use `/find <Movie Name>` or `/movie <Movie Name>`\n"
            "• *Example:* `/find Leo 2023`\n"
            "• *Example:* `/movie Inception`",
            parse_mode="Markdown"
        )
        if update.effective_chat.type != 'private':
            asyncio.create_task(delete_after(msg, 30))
        return

    await execute_movie_search(update, context, query, is_explicit_command=True)

async def search_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 1. Never respond to bots (Welcome bot, Guard bot, Request bot, etc.)
    if update.effective_user and update.effective_user.is_bot:
        return

    # 2. Never respond to anonymous admin / channel posts
    if update.message.sender_chat:
        return

    track_user(update.effective_user)
    # Only listen in groups, supergroups, and private messages (ignore channels)
    if update.effective_chat.type == 'channel':
        return
        
    query = update.message.text
    if not query or len(query.strip()) < 2:
        return

    # Do not treat URLs, web links, or domains as movie search queries
    if re.search(r'(https?://|www\.|\.com\b|\.org\b|\.net\b|\.in\b|t\.me/|telegram\.me/)', query, re.IGNORECASE):
        return

    # Check custom manual keyword filters first
    clean_k = query.strip().lower()
    if filters_collection is not None:
        custom = filters_collection.find_one({"keyword": clean_k})
        if custom:
            await update.message.reply_text(custom.get("reply_text", ""), parse_mode="Markdown")
            return

    # In groups: filter out conversational sentences and casual chat
    is_group = (update.effective_chat.type != 'private')
    if is_group and is_conversational_text(query):
        return

    await execute_movie_search(update, context, query, is_explicit_command=False)


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    track_user(update.effective_user)
    query = update.callback_query
    data = query.data
    
    if data == "ignore":
        await query.answer()
        return
        
    if data.startswith("menu_"):
        parts = data.split("_", 2)
        menu_type = parts[1]
        search_query = parts[2]
        
        if menu_type == "quality":
            reply_markup = build_quality_menu(search_query)
        elif menu_type == "language":
            reply_markup = build_language_menu(search_query)
        elif menu_type == "season":
            reply_markup = build_season_menu(search_query)
            
        try:
            await query.message.edit_reply_markup(reply_markup=reply_markup)
        except Exception:
            pass
        await query.answer()
        return
        
    if data.startswith("apply_"):
        parts = data.split("_", 2)
        filter_val = parts[1]
        search_query = parts[2]
        
        # Stateless filtering by appending keyword
        new_query = f"{search_query} {filter_val}"
        
        results = search_movies(new_query)
        if not results:
            await query.answer(f"❌ No movies found for {filter_val}!", show_alert=True)
            return
            
        reply_markup = build_paginated_keyboard(results, 1, new_query)
        try:
            await query.message.edit_text(
                f"🔍 **Found {len(results)} result(s) for:** `{new_query}`",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
        except Exception:
            pass
        await query.answer(f"Filtered by {filter_val}!")
        return
        
    if data.startswith("page_"):
        parts = data.split("_", 2)
        if len(parts) == 3:
            page = int(parts[1])
            search_query = parts[2]
            
            results = search_movies(search_query)
            if not results:
                await query.answer("Results expired or not found.", show_alert=True)
                return
                
            reply_markup = build_paginated_keyboard(results, page, search_query)
            try:
                await query.message.edit_reply_markup(reply_markup=reply_markup)
            except Exception:
                pass # Message is not modified
        await query.answer()
        return
        
    await query.answer()
    
    if data.startswith("get_"):
        movie_id = data[4:]
        movie = get_movie_by_id(movie_id)
        
        if movie:
            user_id = query.from_user.id
            
            if movie.get("poster_url"):
                caption = f"🎬 **{movie.get('title', 'Unknown')}**\n\n"
                caption += f"⭐ **Rating:** {movie.get('rating', 'N/A')}/10\n"
                caption += f"📅 **Release Date:** {movie.get('release_date', 'N/A')}\n\n"
                caption += f"📖 **Plot:** {str(movie.get('overview', 'No plot available.'))[:500]}..."
                try:
                    await context.bot.send_photo(
                        chat_id=user_id,
                        photo=movie["poster_url"],
                        caption=caption,
                        parse_mode="Markdown"
                    )
                except Exception:
                    pass
                    
            try:
                await context.bot.copy_message(
                    chat_id=user_id,
                    from_chat_id=movie.get('source_chat_id'),
                    message_id=movie.get('source_message_id'),
                    reply_markup=get_watch_keyboard(movie)
                )
                await query.answer("✅ File sent to your Private Messages!", show_alert=True)
            except Exception as e:
                if "Forbidden" in str(e) or "bot can't initiate" in str(e).lower() or "bot was blocked" in str(e).lower():
                    await query.answer("⚠️ Please go to my Private Messages and click START first, then try again!", show_alert=True)
                    return
                try:
                    await context.bot.send_document(
                        chat_id=user_id,
                        document=movie.get('file_id'),
                        caption=movie.get('caption', ''),
                        parse_mode='HTML',
                        reply_markup=get_watch_keyboard(movie)
                    )
                    await query.answer("✅ File sent to your Private Messages!", show_alert=True)
                except Exception as ex:
                    print(f"Error sending file: {ex}")
                    await query.answer(f"🚨 Error Sending File to PM: {ex}", show_alert=True)
        else:
            await query.answer("🚨 Error: This movie was not found in the database. It may have been deleted.", show_alert=True)

async def channel_index_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != 'channel':
        return
        
    msg = update.channel_post
    if not msg:
        return
        
    if not msg.document and not msg.video:
        return
        
    file = msg.document or msg.video
    file_id = file.file_id
    file_name = file.file_name or "Unknown_Movie"
    caption = msg.caption_html if msg.caption else ""
    chat_id = msg.chat.id
    message_id = msg.message_id
    
    # If the file came from another channel, forward a copy to our designated storage channel
    if chat_id != DATABASE_CHANNEL_ID:
        try:
            forwarded_msg = await context.bot.copy_message(
                chat_id=DATABASE_CHANNEL_ID,
                from_chat_id=chat_id,
                message_id=message_id
            )
            chat_id = DATABASE_CHANNEL_ID
            message_id = forwarded_msg.message_id
        except Exception as e:
            print(f"Notice forwarding to storage channel {DATABASE_CHANNEL_ID}: {e}")
            
    add_movie(file_id, file_name, caption, chat_id, message_id, file.file_size)

import asyncio

batch_users = {}

@admin_only
async def batch_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if update.effective_chat.type != 'private':
        return
    batch_users[user_id] = True
    await update.message.reply_text(
        "🏎️ **Batch Indexer Activated!**\n\n"
        "Please go to your Database Channel and **forward the very LAST (newest) message** to me here.\n"
        "(It can be any message, text or movie). I will use its ID to scan the entire channel backwards!",
        parse_mode="Markdown"
    )

async def batch_forward_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not batch_users.get(user_id, False):
        return
        
    msg = update.message
    forward_chat = None
    forward_msg_id = None
    
    # Handle Telegram Bot API 7.0+ (MessageOrigin) and older API (forward_from_chat)
    if hasattr(msg, 'forward_origin') and msg.forward_origin:
        if getattr(msg.forward_origin, 'type', '') == 'channel':
            forward_chat = msg.forward_origin.chat.id
            forward_msg_id = msg.forward_origin.message_id
    elif hasattr(msg, 'forward_from_chat') and msg.forward_from_chat:
        if msg.forward_from_chat.type == 'channel':
            forward_chat = msg.forward_from_chat.id
            forward_msg_id = msg.forward_from_message_id
            
    if not forward_chat:
        await msg.reply_text("⚠️ This message was not forwarded from a channel! Please forward a message from your channel.")
        return
        
    batch_users[user_id] = False
    
    status_msg = await msg.reply_text(f"⏳ **Starting Batch Indexing...**\n\nScanning {forward_msg_id} messages from the channel. Please wait (your screen will flicker as I quickly forward and delete messages).", parse_mode="Markdown")
    
    success_count = 0
    # Process from latest down to 1
    for msg_id in range(forward_msg_id, 0, -1):
        try:
            fwd_msg = await context.bot.forward_message(
                chat_id=update.effective_chat.id,
                from_chat_id=forward_chat,
                message_id=msg_id
            )
            
            if fwd_msg.document or fwd_msg.video:
                file = fwd_msg.document or fwd_msg.video
                file_id = file.file_id
                file_name = file.file_name or "Unknown_Movie"
                caption = fwd_msg.caption_html if fwd_msg.caption else ""
                
                if add_movie(file_id, file_name, caption, forward_chat, msg_id, file.file_size):
                    success_count += 1
                else:
                    if movies_collection is None:
                        await msg.reply_text("🚨 **CRITICAL ERROR:** MongoDB is NOT connected!\nMake sure `MONGODB_URI` is exactly correct in Render Environment Variables.")
                        return
                    
            await fwd_msg.delete()
            await asyncio.sleep(0.3) # Safe rate limit
        except Exception as e:
            if "Chat not found" in str(e) or "unauthorized" in str(e).lower():
                await msg.reply_text("🚨 **ERROR:** I cannot read that channel! Make sure I am an **ADMIN** in the channel.")
                return
            # Message might be deleted in the channel, just skip
            pass
            
    await status_msg.edit_text(f"✅ **Batch Indexing Complete!**\n\nSuccessfully added **{success_count}** new movies to the database.", parse_mode="Markdown")

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if movies_collection is None and alt_movies_collection is None:
        await update.message.reply_text("❌ **MongoDB is NOT connected.**", parse_mode="Markdown")
        return
        
    try:
        primary_count = movies_collection.count_documents({}) if movies_collection is not None else 0
        alt_count = alt_movies_collection.count_documents({}) if alt_movies_collection is not None else 0
        total_movies = primary_count + alt_count
        user_count = users_collection.count_documents({}) if users_collection is not None else 0

        status_text = (
            f"⚡ **CinePrime AutoFilter File Access & Stats:**\n\n"
            f"📁 **Total Accessible Files:** `{total_movies:,}`\n"
            f"• 🎬 **Primary Database ({DATABASE_NAME}):** `{primary_count:,}` files\n"
        )
        if alt_movies_collection is not None:
            status_text += f"• 📦 **Secondary Database ({ALT_DATABASE_NAME}):** `{alt_count:,}` files\n"
        status_text += (
            f"• 👥 **Total Users Tracked:** `{user_count:,}`\n"
            f"• 🤖 **Active Instance:** {curr_cfg.get('name', 'AutoFilter')} (Instance `{instance_key}`)\n"
            f"• 🟢 **System Status:** Online & Active"
        )
        await update.message.reply_text(status_text, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ **MongoDB Error:** {e}")

@admin_only
async def filter_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "❌ **Usage:** `/filter <keyword> <reply_text>`\n"
            "_Example:_ `/filter rules Check group rules before requesting!`",
            parse_mode="Markdown"
        )
        return
    keyword = context.args[0].lower().strip()
    reply_text = " ".join(context.args[1:]).strip()
    if filters_collection is not None:
        filters_collection.update_one(
            {"keyword": keyword},
            {"$set": {"keyword": keyword, "reply_text": reply_text}},
            upsert=True
        )
        await update.message.reply_text(f"✅ Custom filter added for `{keyword}`!", parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ Database not connected.")

@admin_only
async def stop_filter_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ **Usage:** `/stop <keyword>` or `/delfilter <keyword>`", parse_mode="Markdown")
        return
    keyword = context.args[0].lower().strip()
    if filters_collection is not None:
        res = filters_collection.delete_one({"keyword": keyword})
        if res.deleted_count > 0:
            await update.message.reply_text(f"✅ Filter for `{keyword}` has been deleted.", parse_mode="Markdown")
        else:
            await update.message.reply_text(f"⚠️ No filter found for `{keyword}`.", parse_mode="Markdown")

@admin_only
async def list_filters_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if filters_collection is not None:
        docs = list(filters_collection.find().limit(50))
        if not docs:
            await update.message.reply_text("✨ No custom filters configured.")
            return
        lines = ["📋 **Active Custom Filters:**\n"]
        for d in docs:
            lines.append(f"• `{d['keyword']}` ➔ _{d.get('reply_text', '')[:30]}..._")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

@admin_only
async def users_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if users_collection is None:
        await update.message.reply_text("❌ **MongoDB is NOT connected or users collection not initialized.**", parse_mode="Markdown")
        return
        
    try:
        user_count = users_collection.count_documents({})
        await update.message.reply_text(f"👥 **Total Unique Users:** {user_count}", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ **Error fetching users:** {e}")

@admin_only
async def tmdbstatus_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if movies_collection is None:
        return
        
    try:
        total = movies_collection.count_documents({})
        processed = movies_collection.count_documents({"tmdb_processed": True})
        found = movies_collection.count_documents({"tmdb_found": True})
        
        msg = f"🎬 **OMDB Background Status**\n\n"
        msg += f"📊 Total Movies: `{total}`\n"
        msg += f"✅ Processed: `{processed}`\n"
        msg += f"🌟 Posters Found: `{found}`\n"
        msg += f"⏳ Remaining: `{total - processed}`"
        
        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ **Error:** {e}")

@admin_only
async def testposter_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ Please provide a movie name! Example: `/testposter avatar`", parse_mode="Markdown")
        return
        
    query = " ".join(context.args)
    results = search_movies(query)
    
    if not results:
        await update.message.reply_text("❌ That movie is not in your database yet!")
        return
        
    movie = results[0] # Grab the first match
    
    if not movie.get("tmdb_processed"):
        await update.message.reply_text("⏳ The background worker hasn't reached this movie yet. It's still processing! Try another one.", parse_mode="Markdown")
        return
        
    if not movie.get("poster_url"):
        await update.message.reply_text(f"❌ TMDB was checked, but no poster was found for `{movie.get('file_name')}`.", parse_mode="Markdown")
        return
        
    caption = f"🎬 **{movie.get('title', 'Unknown')}**\n\n"
    caption += f"⭐ **Rating:** {movie.get('rating', 'N/A')}/10\n"
    caption += f"📅 **Release Date:** {movie.get('release_date', 'N/A')}\n\n"
    caption += f"📖 **Plot:** {str(movie.get('overview', 'No plot available.'))[:500]}..."
    
    try:
        await update.message.reply_photo(
            photo=movie["poster_url"],
            caption=caption,
            parse_mode="Markdown"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Could not send photo: {e}")

@admin_only
async def exporttmdb_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if movies_collection is None:
        await update.message.reply_text("❌ MongoDB not connected.")
        return
        
    status_msg = await update.message.reply_text("⏳ Generating TMDB completion report...")
    
    try:
        completed = list(movies_collection.find({"tmdb_found": True}))
        failed = list(movies_collection.find({"tmdb_found": False, "tmdb_processed": True}))
        
        report = "=== OMDB ENRICHER EXPORT ===\n\n"
        
        report += f"🌟 POSTERS FOUND ({len(completed)}):\n"
        for c in completed:
            title = c.get('title') or c.get('file_name', 'Unknown')
            report += f"- {title}\n"
            
        report += f"\n❌ POSTERS NOT FOUND ({len(failed)}):\n"
        for f in failed:
            title = f.get('file_name', 'Unknown')
            report += f"- {title}\n"
            
        file_path = "tmdb_export.txt"
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(report)
            
        await context.bot.send_document(
            chat_id=update.effective_chat.id,
            document=open(file_path, 'rb'),
            caption="📊 **OMDB Enrichment Report**",
            parse_mode="Markdown"
        )
        await status_msg.delete()
        os.remove(file_path)
    except Exception as e:
        await status_msg.edit_text(f"❌ Error generating report: {e}")

WELCOME_TEXT = """🎬 **Welcome to CineVault!** 🎬

This is an automated movie search group powered by **CineSearch**.

🔍 **HOW TO SEARCH:**
Just type the name of the movie or series you want to watch directly in this chat!

✅ **Examples:**
• `Avatar`
• `Stranger Things`
• `Loki S01`

💡 **Tips for best results:**
• Check your spelling carefully!
• Do not use years or symbols.
• You can easily filter by Quality, Language, or Season using the interactive buttons that appear after you search!

⚠️ **Note:** To keep this group clean, all searches and results will auto-delete after 1 minute. When you find your movie, click its button and the bot will instantly send the full file directly to your **Private Messages!**

🍿 *Happy Watching!*"""

async def send_daily_welcome(context: ContextTypes.DEFAULT_TYPE):
    if 'config' not in db.list_collection_names():
        return
    config_collection = db['config']
    config = config_collection.find_one({'type': 'welcome_settings'})
    
    if not config or not config.get('chat_id'):
        return
        
    chat_id = config['chat_id']
    old_msg_id = config.get('welcome_msg_id')
    
    if old_msg_id:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=old_msg_id)
        except Exception:
            pass
            
    try:
        new_msg = await context.bot.send_message(
            chat_id=chat_id,
            text=WELCOME_TEXT,
            parse_mode='Markdown'
        )
        try:
            await context.bot.pin_chat_message(chat_id=chat_id, message_id=new_msg.message_id, disable_notification=True)
        except Exception:
            pass
            
        config_collection.update_one(
            {'type': 'welcome_settings'},
            {'$set': {'welcome_msg_id': new_msg.message_id}},
            upsert=True
        )
    except Exception as e:
        print(f"Failed to send daily welcome: {e}")

@admin_only
async def setwelcome_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == 'private':
        await update.message.reply_text("This command must be used in a Group!")
        return
        
    member = await context.bot.get_chat_member(update.effective_chat.id, update.effective_user.id)
    if member.status not in ['creator', 'administrator']:
        await update.message.reply_text("Only admins can use this command!")
        return
        
    if db is None:
        await update.message.reply_text("MongoDB is not connected!")
        return
        
    config_collection = db['config']
    chat_id = update.effective_chat.id
    
    config = config_collection.find_one({'type': 'welcome_settings'})
    if config and config.get('welcome_msg_id'):
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=config['welcome_msg_id'])
        except Exception:
            pass
            
    try:
        new_msg = await update.message.reply_text(WELCOME_TEXT, parse_mode='Markdown')
        try:
            await context.bot.pin_chat_message(chat_id=chat_id, message_id=new_msg.message_id, disable_notification=True)
        except Exception as e:
            await update.message.reply_text(f"⚠️ I could not pin the message. Please make sure I have 'Pin Messages' permission!\nError: {e}")
            
        config_collection.update_one(
            {'type': 'welcome_settings'},
            {'$set': {'chat_id': chat_id, 'welcome_msg_id': new_msg.message_id}},
            upsert=True
        )
        
        # Delete the admin's /setwelcome command message
        try:
            await update.message.delete()
        except Exception:
            pass
            
    except Exception as e:
        await update.message.reply_text(f"Error setting up welcome message: {e}")

import datetime
import pytz
from tmdb_enricher import start_enricher
import threading

async def notify_users_job(context: ContextTypes.DEFAULT_TYPE):
    if scrape_queue is None:
        return
        
    try:
        completed_movies = scrape_queue.find({"status": "completed", "is_urgent": True, "notified": {"$ne": True}})
        for movie in completed_movies:
            movie_name = movie.get("movie_name", "Unknown")
            users = movie.get("requested_by", [])
            
            for user_id in users:
                try:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=f"🎉 **Good News!**\n\nThe movie **{movie_name}** you requested is now available!\nClick the button below to get it.",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("🔍 Search Now", switch_inline_query_current_chat=movie_name)
                        ]]),
                        parse_mode="Markdown"
                    )
                except Exception as e:
                    print(f"Failed to notify user {user_id}: {e}")
                    
            scrape_queue.delete_one({"_id": movie["_id"]})
    except Exception as e:
        print(f"Error in notify_users_job: {e}")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🤖 **CinePrime AutoFilter Bot — Management & Usage Guide**\n\n"
        "🎬 **How to Search for Movies & Series:**\n"
        "• Send the movie name in the group or in this chat!\n"
        "• _Example:_ `Leo 2023` or `Jailer` or `Loki S01`\n"
        "• Use interactive buttons to filter by **Quality** (1080p, 720p, 480p), **Language**, or **Season**.\n"
        "• Click on any movie button to receive the file in your Private Messages.\n\n"
        "🛠 **Admin In-Chat Management Commands:**\n"
        "• `/status` — View total indexed movies (170k+), users, and database health\n"
        "• `/claim` — Claim ownership of the bot in this chat\n"
        "• `/batch` — Batch index an entire channel backwards from a forwarded message\n"
        "• `/filter <keyword> <reply>` — Set a custom keyword trigger\n"
        "• `/filters` — View all active custom filters\n"
        "• `/stop <keyword>` — Delete a custom keyword filter\n"
        "• `/users` — View total unique users\n"
        "• `/tmdbstatus` — Check TMDB poster enrichment coverage"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

def main():
    threading.Thread(target=start_enricher, daemon=True).start()
    
    application = Application.builder().token(TOKEN).post_init(post_init).build()
    
    # Schedule daily job at 4:00 AM IST
    ist = pytz.timezone('Asia/Kolkata')
    target_time = datetime.time(hour=4, minute=0, tzinfo=ist)
    try:
        application.job_queue.run_daily(send_daily_welcome, time=target_time)
        application.job_queue.run_repeating(notify_users_job, interval=30)
    except AttributeError:
        print("Warning: JobQueue is not installed properly. Daily welcome messages are disabled.")
    except Exception as e:
        print(f"Warning: Failed to schedule daily welcome: {e}")
    
    application.add_handler(CommandHandler('start', start_handler))
    application.add_handler(CommandHandler('help', help_command))
    application.add_handler(CommandHandler('whereami', whereami_command))
    application.add_handler(CommandHandler('claim', claim_command))
    application.add_handler(CommandHandler('batch', batch_command))
    application.add_handler(CommandHandler(['status', 'stats', 'total', 'files', 'count'], status_command))
    application.add_handler(CommandHandler('users', users_command))
    application.add_handler(CommandHandler('filter', filter_command))
    application.add_handler(CommandHandler('filters', list_filters_command))
    application.add_handler(CommandHandler('stop', stop_filter_command))
    application.add_handler(CommandHandler('delfilter', stop_filter_command))
    application.add_handler(CommandHandler('tmdbstatus', tmdbstatus_command))
    application.add_handler(CommandHandler('testposter', testposter_command))
    application.add_handler(CommandHandler('exporttmdb', exporttmdb_command))
    application.add_handler(CommandHandler('setwelcome', setwelcome_command))
    application.add_handler(CommandHandler(['find', 'movie', 'search', 'f', 'm'], movie_command_handler))
    
    # Catch forwarded messages for batch indexer (must be BEFORE index_movie_handler to intercept correctly if needed)
    application.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.FORWARDED, batch_forward_handler))
    
    # In private, listen for media to index manually
    application.add_handler(MessageHandler(filters.ChatType.PRIVATE & (filters.Document.ALL | filters.VIDEO), index_movie_handler))
    
    # In channels, listen for NEW media to index automatically
    application.add_handler(MessageHandler(filters.ChatType.CHANNEL & (filters.Document.ALL | filters.VIDEO), channel_index_handler))
    
    # In groups and private chats, listen for text to search
    application.add_handler(MessageHandler((filters.ChatType.GROUPS | filters.ChatType.PRIVATE) & filters.TEXT & ~filters.COMMAND, search_handler))
    
    # Handle inline buttons
    application.add_handler(CallbackQueryHandler(button_callback))
    
    application.run_polling(drop_pending_updates=True)

import asyncio
import sys
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

if __name__ == '__main__':
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    main()

