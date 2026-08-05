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

# --- Database Layer (JSON) ---
DB_FILE = 'movies.json'

def load_db():
    try:
        with open(DB_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def save_db(data):
    with open(DB_FILE, 'w') as f:
        json.dump(data, f, indent=4)

def add_movie(file_id, file_name, caption_html, from_chat_id, message_id):
    db = load_db()
    for item in db:
        if item['file_id'] == file_id:
            return False
            
    movie = {
        'id': str(uuid.uuid4()),
        'file_id': file_id,
        'file_name': file_name,
        'caption': caption_html,
        'source_chat_id': from_chat_id,
        'source_message_id': message_id
    }
    db.append(movie)
    save_db(db)
    return True

def search_movies(query):
    db = load_db()
    results = []
    # Split query into words for better matching
    words = query.lower().split()
    for item in db:
        name_lower = item['file_name'].lower()
        # If all words in query are in the filename
        if all(word in name_lower for word in words):
            results.append(item)
    return results

def get_movie_by_id(movie_id):
    db = load_db()
    for item in db:
        if item['id'] == movie_id:
            return item
    return None

# --- Telegram Handlers ---

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == 'private':
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
    else:
        await msg.reply_text("⚠️ This file is already in the database.")

async def group_search_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Only listen in groups or supergroups
    if update.effective_chat.type in ['private', 'channel']:
        return
        
    query = update.message.text
    if not query or len(query) < 3:
        return
        
    results = search_movies(query)
    if not results:
        return
        
    keyboard = []
    # Limit to top 5 results to avoid massive messages
    for movie in results[:5]:
        btn_text = movie['file_name']
        if len(btn_text) > 40:
            btn_text = btn_text[:37] + "..."
        keyboard.append([InlineKeyboardButton(f"🎬 {btn_text}", callback_data=f"get_{movie['id']}")])
        
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"🔍 **Found {len(results)} result(s) for:** `{query}`",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    if data.startswith("get_"):
        movie_id = data[4:]
        movie = get_movie_by_id(movie_id)
        
        if not movie:
            await query.message.reply_text("❌ Movie not found in database anymore.")
            return
            
        try:
            # We use copy_message if possible because it's the safest way to preserve everything
            await context.bot.copy_message(
                chat_id=query.message.chat_id,
                from_chat_id=movie['source_chat_id'],
                message_id=movie['source_message_id']
            )
        except Exception as e:
            # Fallback to file_id sending
            try:
                await context.bot.send_document(
                    chat_id=query.message.chat_id,
                    document=movie['file_id'],
                    caption=movie['caption'],
                    parse_mode="HTML"
                )
            except Exception as e2:
                await context.bot.send_message(chat_id=query.message.chat_id, text=f"❌ Error sending file.")

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
                    
            await fwd_msg.delete()
            await asyncio.sleep(0.3) # Safe rate limit
        except Exception:
            # Message might be deleted in the channel, just skip
            pass
            
    await status_msg.edit_text(f"✅ **Batch Indexing Complete!**\n\nSuccessfully added **{success_count}** movies to the database.", parse_mode="Markdown")

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

def main():
    threading.Thread(target=run_dummy_server, daemon=True).start()
    
    application = Application.builder().token(TOKEN).build()
    
    application.add_handler(CommandHandler('start', start_handler))
    application.add_handler(CommandHandler('batch', batch_command))
    
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
