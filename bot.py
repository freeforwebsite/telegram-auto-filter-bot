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
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")

import pymongo

MONGODB_URI = os.environ.get("MONGODB_URI", "")
client = None
db = None
movies_collection = None

if MONGODB_URI:
    try:
        client = pymongo.MongoClient(MONGODB_URI)
        db = client['telegram_bot']
        movies_collection = db['movies']
    except Exception as e:
        print(f"MongoDB Connection Error: {e}")

def add_movie(file_id, file_name, caption_html, from_chat_id, message_id):
    if movies_collection is None:
        print("WARNING: MongoDB not connected. Cannot add movie.")
        return False
        
    # Check if file already exists
    if movies_collection.find_one({'file_id': file_id}):
        return False
        
    movie = {
        'id': str(uuid.uuid4()),
        'file_id': file_id,
        'file_name': file_name,
        'caption': caption_html,
        'source_chat_id': from_chat_id,
        'source_message_id': message_id
    }
    
    movies_collection.insert_one(movie)
    return True

import re

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
    if movies_collection is None:
        return []
        
    # Extract alphanumeric words from the query
    words = re.findall(r'[a-zA-Z0-9]+', query)
    if not words:
        return []
        
    # Create a regex condition for every word (case-insensitive)
    conditions = []
    for word in words:
        conditions.append({"file_name": {"$regex": word, "$options": "i"}})
        
    # Let MongoDB do the heavy lifting! (Find matching all words, limit to 100)
    try:
        cursor = movies_collection.find({"$and": conditions}).limit(100)
        results = list(cursor)
        return results
    except Exception as e:
        print(f"MongoDB Search Error: {e}")
        return []

def get_movie_by_id(movie_id):
    if movies_collection is None:
        return None
    return movies_collection.find_one({'id': movie_id})

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == 'private':
        # Check for deep link request: /start get_uuid
        text = update.message.text
        if len(text.split()) > 1:
            arg = text.split()[1]
            if arg.startswith("get_"):
                movie_id = arg[4:]
                movie = get_movie_by_id(movie_id)
                if movie:
                    try:
                        await context.bot.copy_message(
                            chat_id=update.effective_chat.id,
                            from_chat_id=movie['source_chat_id'],
                            message_id=movie['source_message_id']
                        )
                    except Exception as e:
                        try:
                            await context.bot.send_document(
                                chat_id=update.effective_chat.id,
                                document=movie['file_id'],
                                caption=movie.get('caption', ''),
                                parse_mode='HTML'
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
    
    success = add_movie(file_id, file_name, caption, msg.chat.id, msg.message_id)
    if success:
        await msg.reply_text(f"✅ **Saved to Database!**\n\nName: `{file_name}`", parse_mode="Markdown")
        
        # 🌟 NEW: Forward a physical backup of the file to the Database Channel!
        try:
            await context.bot.copy_message(
                chat_id=-1003975570574,
                from_chat_id=msg.chat.id,
                message_id=msg.message_id
            )
        except Exception as e:
            print(f"Failed to backup to Database Channel: {e}")
            
    else:
        await msg.reply_text("⚠️ This file is already in the database.")

BOT_USERNAME = None

async def post_init(application: Application):
    global BOT_USERNAME
    BOT_USERNAME = application.bot.username
    print(f"Bot Username: {BOT_USERNAME}")

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
        btn_text = movie['file_name']
        if len(btn_text) > 40:
            btn_text = btn_text[:37] + "..."
        
        # Use deep linking to redirect to bot PM
        if BOT_USERNAME:
            url = f"https://t.me/{BOT_USERNAME}?start=get_{movie['id']}"
            keyboard.append([InlineKeyboardButton(f"🎬 {btn_text}", url=url)])
        else:
            keyboard.append([InlineKeyboardButton(f"🎬 {btn_text}", callback_data=f"get_{movie['id']}")])
        
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

async def group_search_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Only listen in groups or supergroups
    if update.effective_chat.type in ['private', 'channel']:
        return
        
    query = update.message.text
    # Ignore messages that are too short, or too long (like Welcome Messages and Admin announcements)
    if not query or len(query) < 3 or len(query) > 60:
        return
        
    # 🌟 INSTANT FEEDBACK
    searching_msg = await update.message.reply_text(f"🔎 ꜱᴇᴀʀᴄʜɪɴɢ `{query}`", parse_mode="Markdown")
        
    results = search_movies(query)
    
    if not results:
        not_found_text = (
            f"❌ **Movie Not Found!**\n\n"
            f"I couldn't find anything matching: `{query}`\n\n"
            "💡 **Search Tips:**\n"
            "• Check your spelling carefully!\n"
            "• **Movie:** `Jawan` or `Jawan 2023`\n"
            "• **Series:** `Loki S01` or `Loki S01E04`\n"
            "• **Don't use:** `: ! ( ) , . /`"
        )
        google_url = f"https://www.google.com/search?q={urllib.parse.quote(query)}"
        keyboard = [[InlineKeyboardButton("🔍 DO GOOGLE", url=google_url)]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await searching_msg.edit_text(
            not_found_text, 
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        # Auto-delete BOTH the user's message and bot's message after 60s
        asyncio.create_task(delete_after(update.message, 60))
        asyncio.create_task(delete_after(searching_msg, 60))
        return
        
    short_query = query[:40]
    reply_markup = build_paginated_keyboard(results, 1, short_query)
    
    await searching_msg.edit_text(
        f"🔍 **Found {len(results)} result(s) for:** `{query}`",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )
    # Auto-delete BOTH the user's message and bot's message after 60s
    asyncio.create_task(delete_after(update.message, 60))
    asyncio.create_task(delete_after(searching_msg, 60))

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            try:
                await context.bot.copy_message(
                    chat_id=user_id,
                    from_chat_id=movie['source_chat_id'],
                    message_id=movie['source_message_id']
                )
                await query.answer("✅ File sent to your Private Messages!", show_alert=True)
            except Exception as e:
                if "Forbidden" in str(e) or "bot can't initiate" in str(e).lower() or "bot was blocked" in str(e).lower():
                    await query.answer("⚠️ Please go to my Private Messages and click START first, then try again!", show_alert=True)
                    return
                try:
                    await context.bot.send_document(
                        chat_id=user_id,
                        document=movie['file_id'],
                        caption=movie.get('caption', ''),
                        parse_mode='HTML'
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
    
    # Automatically add to database
    add_movie(file_id, file_name, caption, msg.chat.id, msg.message_id)

import asyncio

batch_users = {}

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
                
                if add_movie(file_id, file_name, caption, forward_chat, msg_id):
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
    if movies_collection is None:
        await update.message.reply_text("❌ **MongoDB is NOT connected.**", parse_mode="Markdown")
        return
        
    try:
        count = movies_collection.count_documents({})
        await update.message.reply_text(f"✅ **MongoDB is Connected!**\n\nTotal movies in database: **{count}**", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ **MongoDB Error:** {e}")

async def tmdbstatus_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if movies_collection is None:
        return
        
    try:
        total = movies_collection.count_documents({})
        processed = movies_collection.count_documents({"tmdb_processed": True})
        found = movies_collection.count_documents({"tmdb_found": True})
        
        msg = f"🎬 **TMDB Background Status**\n\n"
        msg += f"📊 Total Movies: `{total}`\n"
        msg += f"✅ Processed: `{processed}`\n"
        msg += f"🌟 Posters Found: `{found}`\n"
        msg += f"⏳ Remaining: `{total - processed}`"
        
        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ **Error:** {e}")

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

# --- Dummy Web Server for Render ---
class DummyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Auto Filter Bot is running")

def run_dummy_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), DummyHandler)
    server.serve_forever()

import datetime
import pytz
from tmdb_enricher import start_enricher

def main():
    threading.Thread(target=run_dummy_server, daemon=True).start()
    threading.Thread(target=start_enricher, daemon=True).start()
    
    application = Application.builder().token(TOKEN).post_init(post_init).build()
    
    # Schedule daily job at 4:00 AM IST
    ist = pytz.timezone('Asia/Kolkata')
    target_time = datetime.time(hour=4, minute=0, tzinfo=ist)
    application.job_queue.run_daily(send_daily_welcome, time=target_time)
    
    application.add_handler(CommandHandler('start', start_handler))
    application.add_handler(CommandHandler('batch', batch_command))
    application.add_handler(CommandHandler('status', status_command))
    application.add_handler(CommandHandler('tmdbstatus', tmdbstatus_command))
    application.add_handler(CommandHandler('testposter', testposter_command))
    application.add_handler(CommandHandler('setwelcome', setwelcome_command))
    
    # Catch forwarded messages for batch indexer (must be BEFORE index_movie_handler to intercept correctly if needed)
    application.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.FORWARDED, batch_forward_handler))
    
    # In private, listen for media to index manually
    application.add_handler(MessageHandler(filters.ChatType.PRIVATE & (filters.Document.ALL | filters.VIDEO), index_movie_handler))
    
    # In channels, listen for NEW media to index automatically
    application.add_handler(MessageHandler(filters.ChatType.CHANNEL & (filters.Document.ALL | filters.VIDEO), channel_index_handler))
    
    # In groups, listen for text to search
    application.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND, group_search_handler))
    
    # Handle inline buttons
    application.add_handler(CallbackQueryHandler(button_callback))
    
    application.run_polling()

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
