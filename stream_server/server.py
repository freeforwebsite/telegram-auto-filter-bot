import os
import re
import math
import logging
from aiohttp import web
from pyrogram import Client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

API_ID = int(os.environ.get('API_ID', 36869346))
API_HASH = os.environ.get('API_HASH', '9abc474ef05c5e46b2210b02eb4c81fc')
BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
MONGO_URI = os.environ.get('MONGODB_URI')

# MongoDB Setup
from motor.motor_asyncio import AsyncIOMotorClient
db_client = AsyncIOMotorClient(MONGO_URI)
movies_col = db_client['telegram_bot']['movies']

USERBOT_SESSION = os.environ.get('USERBOT_SESSION')

# Initialize Pyrogram Client for Streaming
if USERBOT_SESSION:
    stream_client = Client(
        "stream_userbot",
        api_id=API_ID,
        api_hash=API_HASH,
        session_string=USERBOT_SESSION,
        in_memory=True
    )
    logger.info("Stream Server using USERBOT_SESSION for unrestricted file streaming!")
else:
    stream_client = Client(
        "stream_bot",
        api_id=API_ID,
        api_hash=API_HASH,
        bot_token=BOT_TOKEN,
        in_memory=True
    )
    logger.warning("Stream Server using BOT_TOKEN. Streaming is limited to 20MB files! Please provide USERBOT_SESSION.")

class StreamServer:
    def __init__(self, client: Client):
        self.client = client
        self.app = web.Application()
        self.app.router.add_get('/', self.health_check)
        self.app.router.add_get('/watch/{file_id}/{filename}', self.stream_handler)
        self.app.router.add_get('/player/{file_id}/{filename}', self.player_page)
        self.app.router.add_get('/thumb/{file_id}', self.thumb_handler)

    async def health_check(self, request):
        return web.Response(text="Streaming Server is Running!")

    async def player_page(self, request):
        file_id = request.match_info['file_id']
        filename = request.match_info['filename']
        
        # We will load the sleek HTML player here
        html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Watch: {filename}</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css"/>
    <link rel="stylesheet" href="https://cdn.plyr.io/3.7.8/plyr.css" />
    <style>
        :root {{
            --bg-color: #000000;
            --text-primary: #ffffff;
            --text-secondary: rgba(255,255,255,0.6);
            --accent: #E50914; /* Netflix Red style accent */
            --glass: rgba(20,20,20,0.85);
        }}

        *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

        body {{
            font-family: 'Inter', sans-serif;
            background-color: var(--bg-color);
            color: var(--text-primary);
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            overflow-x: hidden;
        }}

        /* Top Navigation Bar */
        .navbar {{
            padding: 20px 40px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            background: linear-gradient(to bottom, rgba(0,0,0,0.9) 0%, transparent 100%);
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            z-index: 10;
        }}

        .logo {{
            font-size: 24px;
            font-weight: 600;
            letter-spacing: -0.5px;
            color: var(--accent);
        }}
        
        .logo span {{
            color: #fff;
        }}

        /* Main Player Area */
        .player-section {{
            flex-grow: 1;
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
            width: 100%;
            max-width: 1200px;
            margin: 0 auto;
            padding: 80px 20px 40px;
        }}

        .video-wrapper {{
            width: 100%;
            border-radius: 12px;
            overflow: hidden;
            box-shadow: 0 20px 60px rgba(0,0,0,0.8);
            background: #050505;
        }}

        /* Customizing Plyr for a more minimal look */
        :root {{
            --plyr-color-main: var(--accent);
            --plyr-video-background: #000;
        }}

        /* Movie Info Below Player */
        .movie-info {{
            width: 100%;
            margin-top: 30px;
            display: flex;
            flex-direction: column;
            gap: 15px;
        }}

        .movie-title {{
            font-size: 24px;
            font-weight: 400;
            line-height: 1.4;
            color: var(--text-primary);
        }}

        .movie-meta {{
            display: flex;
            gap: 15px;
            font-size: 14px;
            color: var(--text-secondary);
            align-items: center;
        }}

        .badge {{
            border: 1px solid rgba(255,255,255,0.3);
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 12px;
            font-weight: 600;
            text-transform: uppercase;
        }}

        /* Actions Row */
        .actions-row {{
            display: flex;
            gap: 15px;
            margin-top: 20px;
            flex-wrap: wrap;
        }}

        .btn {{
            display: inline-flex;
            align-items: center;
            gap: 10px;
            padding: 12px 24px;
            border-radius: 6px;
            font-size: 15px;
            font-weight: 600;
            text-decoration: none;
            transition: all 0.2s ease;
            cursor: pointer;
            border: none;
        }}

        .btn-primary {{
            background-color: var(--text-primary);
            color: var(--bg-color);
        }}

        .btn-primary:hover {{
            background-color: rgba(255,255,255,0.8);
        }}

        .btn-secondary {{
            background-color: rgba(255,255,255,0.1);
            color: var(--text-primary);
        }}

        .btn-secondary:hover {{
            background-color: rgba(255,255,255,0.2);
        }}

        /* Responsive */
        @media (max-width: 768px) {{
            .navbar {{ padding: 15px 20px; }}
            .player-section {{ padding-top: 70px; }}
            .movie-title {{ font-size: 20px; }}
            .actions-row {{ width: 100%; flex-direction: column; }}
            .btn {{ width: 100%; justify-content: center; }}
        }}
    </style>
</head>
<body>

    <div class="navbar">
        <div class="logo">Cine<span>Search</span></div>
    </div>

    <div class="player-section">
        <div class="video-wrapper">
            <video id="player" poster="/thumb/{file_id}" playsinline controls>
                <source src="/watch/{file_id}/{filename}" type="video/mp4" />
            </video>
        </div>

        <div class="movie-info">
            <h1 class="movie-title">{filename}</h1>
            <div class="movie-meta">
                <span class="badge">HD</span>
                <span><i class="fas fa-shield-alt"></i> Secure Stream</span>
            </div>
            
            <div class="actions-row">
                <a href="/watch/{file_id}/{filename}" download="{filename}" class="btn btn-primary">
                    <i class="fas fa-download"></i> Download File
                </a>
                <a href="https://t.me/MoviiWrld" target="_blank" class="btn btn-secondary">
                    <i class="fab fa-telegram-plane"></i> Join CineVault
                </a>
            </div>
        </div>
    </div>

    <script src="https://cdn.plyr.io/3.7.8/plyr.js"></script>
    <script>
        const player = new Plyr('#player', {{
            controls: ['play-large', 'play', 'progress', 'current-time', 'duration', 'mute', 'volume', 'captions', 'settings', 'pip', 'airplay', 'fullscreen'],
            settings: ['captions', 'quality', 'speed', 'loop']
        }});
    </script>
</body>
</html>
"""
        return web.Response(text=html_content, content_type='text/html')

    async def stream_handler(self, request):
        file_id = request.match_info['file_id']
        filename = request.match_info['filename']
        
        try:
            # 1. Look up the movie in MongoDB to get source_chat_id and source_message_id
            movie = await movies_col.find_one({'file_id': file_id})
            if not movie:
                return web.Response(status=404, text="Movie not found in database")
                
            source_chat_id = movie.get('source_chat_id')
            source_message_id = movie.get('source_message_id')
            
            # Critical Fix: If the movie was stored from a private chat, the source_chat_id is the user's ID.
            # But the Userbot needs to query the Bot's chat ID to find the message!
            if source_chat_id and source_chat_id > 0:
                bot_id = int(BOT_TOKEN.split(':')[0])
                source_chat_id = bot_id
            
            # 2. Fetch the message using Pyrogram to get the exact file_size
            msg = await self.client.get_messages(source_chat_id, source_message_id)
            
            if not msg or msg.empty:
                logger.error(f"Failed to fetch message {source_message_id} from chat {source_chat_id}")
                return web.Response(status=404, text="Original message not found in Telegram")
                
            media = msg.document or msg.video
            if not media:
                return web.Response(status=404, text="Message does not contain media")
                
            file_size = media.file_size
            
            # 3. Handle Range Requests
            range_header = request.headers.get('Range', 0)
            
            if range_header:
                match = re.search(r'bytes=(\d+)-(\d*)', range_header)
                if match:
                    offset = int(match.group(1))
                    end = int(match.group(2)) if match.group(2) else file_size - 1
                else:
                    offset = 0
                    end = file_size - 1
            else:
                offset = 0
                end = file_size - 1
                
            length = end - offset + 1
            
            mime_type = getattr(media, 'mime_type', 'video/mp4')
            if mime_type == 'video/x-matroska':
                # Browsers handle mkv better if masqueraded as webm since WebM is based on Matroska.
                mime_type = 'video/webm'
                
            headers = {
                'Content-Type': mime_type,
                'Accept-Ranges': 'bytes',
                'Content-Range': f'bytes {offset}-{end}/{file_size}',
                'Content-Length': str(length),
                'Content-Disposition': f'inline; filename="{filename}"'
            }
            
            response = web.StreamResponse(
                status=206 if range_header else 200,
                headers=headers
            )
            await response.prepare(request)
            
            # Stream from Pyrogram using the message object directly
            async for chunk in self.client.stream_media(msg, limit=length, offset=offset):
                try:
                    await response.write(chunk)
                except Exception:
                    # Client disconnected (closed tab, paused, or seeked)
                    break
                    
            return response
            
        except Exception as e:
            logger.error(f"Stream Error: {{e}}")
            return web.Response(status=500, text="Streaming Failed")


    async def thumb_handler(self, request):
        file_id = request.match_info['file_id']
        try:
            movie = await movies_col.find_one({'file_id': file_id})
            if not movie:
                return web.Response(status=404)
                
            # 1. Try to fetch TMDB Poster First
            import aiohttp
            import re
            
            # Helper to clean filename
            def clean_title(filename):
                name = re.sub(r'\.(mkv|mp4|avi|webm)$', '', filename, flags=re.IGNORECASE)
                
                # Strip out brackets completely
                name = re.sub(r'\[.*?\]', '', name)
                name = re.sub(r'\(.*?\)', '', name)
                
                # Strip Season/Episode formats like S05, S05E07, Season 5, Ep 4
                name = re.sub(r'(?i)(s\d{2}e\d{2}|s\d{2}|season\s*\d+|ep\s*\d+|e\d{2})', '', name)
                
                # Tags to strip (with word boundaries!)
                tags = [r'1080p', r'720p', r'480p', r'2160p', r'4k', r'x264', r'x265', r'hevc', r'avc', r'10bit', r'hdr', r'webrip', r'web-dl', r'hdrip', r'bluray', r'brrip', r'dvdrip', r'hdtv', r'web', r'dl', r'tamil', r'telugu', r'hindi', r'malayalam', r'kannada', r'english', r'multi', r'audio', r'dual', r'sub', r'esub', r'msub', r'untouched', r'esubs', r'hq', r'line', r'predvd', r'nf', r'ta', r'ddp\d\.\d']
                
                for tag in tags:
                    name = re.sub(rf'\b{tag}\b', '', name, flags=re.IGNORECASE)
                    
                name = re.sub(r'[\._\-]', ' ', name)
                name = re.sub(r'@\w+', '', name)
                name = re.sub(r'(?i)t me\S*', '', name)
                
                # Clean up multiple spaces
                name = re.sub(r'\s+', ' ', name).strip()
                
                return name
                
            clean_name = clean_title(movie.get('file_name', ''))
            
            if clean_name:
                tmdb_api_key = "74683f7b34f7b689d84fcd8e0016d82a"
                search_url = f"https://api.themoviedb.org/3/search/movie?api_key={tmdb_api_key}&query={clean_name}"
                
                async with aiohttp.ClientSession() as session:
                    async with session.get(search_url) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            if data.get('results') and len(data['results']) > 0:
                                poster_path = data['results'][0].get('poster_path')
                                if poster_path:
                                    poster_url = f"https://image.tmdb.org/t/p/w500{poster_path}"
                                    # Redirect to TMDB image!
                                    return web.HTTPFound(location=poster_url)
            
            # 2. Fallback to Telegram Video Thumbnail
            source_chat_id = movie.get('source_chat_id')
            source_message_id = movie.get('source_message_id')
            
            if source_chat_id and source_chat_id > 0:
                bot_id = int(BOT_TOKEN.split(':')[0])
                source_chat_id = bot_id
                
            msg = await self.client.get_messages(source_chat_id, source_message_id)
            if not msg or msg.empty:
                return web.Response(status=404)
                
            media = msg.document or msg.video
            if not media or not getattr(media, 'thumbs', None):
                transparent_gif = b'\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00\x21\xf9\x04\x01\x00\x00\x00\x00\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x44\x01\x00\x3b'
                return web.Response(body=transparent_gif, content_type='image/gif')
                
            thumb = media.thumbs[-1]
            thumb_file_id = thumb.file_id
            
            thumb_bytes = await self.client.download_media(thumb_file_id, in_memory=True)
            if not thumb_bytes:
                return web.Response(status=404)
                
            return web.Response(body=thumb_bytes.getvalue(), content_type='image/jpeg')
        except Exception as e:
            logger.error(f"Thumb Error: {e}")
            return web.Response(status=500)

async def start_stream_server():
    logger.info("Starting Pyrogram Client for Streaming...")
    await stream_client.start()
    
    server = StreamServer(stream_client)
    
    # Use Render's PORT environment variable
    port = int(os.environ.get("PORT", 8080))
    runner = web.AppRunner(server.app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    
    logger.info(f"Stream Server listening on port {{port}}...")
    await site.start()
