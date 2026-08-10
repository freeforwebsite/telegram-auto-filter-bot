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
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css"/>
    <link rel="stylesheet" href="https://cdn.plyr.io/3.7.8/plyr.css" />
    <style>
        :root {{
            --bg-deep: #0D0D14;
            --bg-surface: #14141F;
            --bg-elevated: #1F1F2E;
            --primary: #8B5CF6; /* Purple accent */
            --primary-hover: #7C3AED;
            --text-main: #FFFFFF;
            --text-muted: rgba(255,255,255,0.6);
            --border: rgba(255,255,255,0.08);
            --success: #10B981;
        }}

        *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

        body {{
            font-family: 'Inter', sans-serif;
            background-color: var(--bg-deep);
            color: var(--text-main);
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            overflow-x: hidden;
            position: relative;
        }}
        
        /* Subtle Background Gradient Grid */
        body::before {{
            content: '';
            position: fixed;
            inset: 0;
            background-image: 
                linear-gradient(rgba(255,255,255,0.03) 1px, transparent 1px),
                linear-gradient(90deg, rgba(255,255,255,0.03) 1px, transparent 1px);
            background-size: 50px 50px;
            pointer-events: none;
            z-index: 0;
        }}
        
        body::after {{
            content: '';
            position: fixed;
            inset: 0;
            background: radial-gradient(circle at 50% 0%, rgba(139, 92, 246, 0.15) 0%, transparent 70%);
            pointer-events: none;
            z-index: 0;
        }}

        /* Header */
        .header {{
            position: relative;
            z-index: 10;
            padding: 24px 40px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}

        .brand {{
            display: flex;
            align-items: center;
            gap: 12px;
            font-size: 20px;
            font-weight: 700;
            color: var(--text-main);
        }}
        
        .brand-icon {{
            width: 36px;
            height: 36px;
            background: linear-gradient(135deg, #8B5CF6, #EC4899);
            border-radius: 10px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 16px;
        }}

        .header-actions {{
            display: flex;
            gap: 12px;
        }}
        
        .badge-secure {{
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 8px 16px;
            background: rgba(16, 185, 129, 0.1);
            border: 1px solid rgba(16, 185, 129, 0.2);
            border-radius: 100px;
            font-size: 13px;
            font-weight: 600;
            color: var(--success);
        }}
        
        .btn-join {{
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 8px 20px;
            background: linear-gradient(135deg, #8B5CF6, #EC4899);
            border-radius: 100px;
            font-size: 14px;
            font-weight: 600;
            color: white;
            text-decoration: none;
            border: none;
            cursor: pointer;
            transition: opacity 0.2s;
        }}
        
        .btn-join:hover {{
            opacity: 0.9;
        }}

        /* Main Content */
        .container {{
            position: relative;
            z-index: 10;
            flex: 1;
            display: flex;
            flex-direction: column;
            align-items: center;
            padding: 20px 20px 60px;
            width: 100%;
            max-width: 900px;
            margin: 0 auto;
        }}

        /* Player Card */
        .player-card {{
            width: 100%;
            background: var(--bg-surface);
            border: 1px solid var(--border);
            border-radius: 20px;
            padding: 24px;
            box-shadow: 0 25px 50px -12px rgba(0,0,0,0.5);
            margin-bottom: 24px;
        }}
        
        .player-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
        }}
        
        .status-indicator {{
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 6px 14px;
            background: rgba(16, 185, 129, 0.1);
            border-radius: 100px;
            font-size: 12px;
            font-weight: 600;
            color: var(--success);
        }}
        
        .status-dot {{
            width: 6px;
            height: 6px;
            background: var(--success);
            border-radius: 50%;
            box-shadow: 0 0 8px var(--success);
        }}

        .video-wrapper {{
            width: 100%;
            border-radius: 12px;
            overflow: hidden;
            background: #000;
            border: 1px solid rgba(255,255,255,0.05);
            box-shadow: 0 10px 30px rgba(0,0,0,0.5);
            position: relative;
        }}
        
        /* Force Plyr video to maintain aspect ratio and not stretch */
        .plyr__video-wrapper video {{
            object-fit: contain !important;
            width: 100% !important;
            height: auto !important;
            max-height: 70vh !important;
        }}

        /* Customizing Plyr for a more minimal look */
        :root {{
            --plyr-color-main: var(--primary);
            --plyr-video-background: #000;
            --plyr-menu-background: var(--bg-elevated);
            --plyr-menu-color: var(--text-main);
        }}

        /* Info Card */
        .info-card {{
            width: 100%;
            background: var(--bg-surface);
            border: 1px solid var(--border);
            border-radius: 20px;
            padding: 24px;
            display: flex;
            flex-direction: column;
            gap: 20px;
        }}
        
        .file-info {{
            display: flex;
            flex-direction: column;
            gap: 8px;
        }}
        
        .file-id {{
            font-size: 12px;
            font-weight: 700;
            color: var(--text-muted);
            letter-spacing: 1px;
        }}
        
        .file-name {{
            font-size: 16px;
            font-weight: 500;
            color: var(--text-main);
            word-break: break-all;
        }}
        
        .tags {{
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
        }}
        
        .tag {{
            display: flex;
            align-items: center;
            gap: 6px;
            padding: 6px 12px;
            background: rgba(255,255,255,0.05);
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 100px;
            font-size: 12px;
            font-weight: 500;
            color: var(--text-muted);
        }}
        
        .tag i {{
            color: var(--primary);
        }}

        .btn-download {{
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 10px;
            width: 100%;
            padding: 16px;
            background: linear-gradient(135deg, #8B5CF6, #EC4899);
            border-radius: 14px;
            font-size: 16px;
            font-weight: 600;
            color: white;
            text-decoration: none;
            border: none;
            cursor: pointer;
            transition: transform 0.2s, box-shadow 0.2s;
            box-shadow: 0 10px 20px rgba(139, 92, 246, 0.3);
        }}
        
        .btn-download:hover {{
            transform: translateY(-2px);
            box-shadow: 0 15px 25px rgba(139, 92, 246, 0.4);
        }}
        
        .external-players {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 15px;
            margin-top: 10px;
        }}
        
        .btn-external {{
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            gap: 8px;
            padding: 16px;
            background: rgba(255,255,255,0.03);
            border: 1px solid var(--border);
            border-radius: 14px;
            font-size: 13px;
            font-weight: 500;
            color: var(--text-muted);
            cursor: pointer;
            transition: all 0.2s;
        }}
        
        .btn-external i {{
            font-size: 20px;
            color: var(--text-main);
        }}
        
        .btn-external:hover {{
            background: rgba(255,255,255,0.08);
            border-color: rgba(255,255,255,0.2);
            color: var(--text-main);
        }}

        /* Responsive */
        @media (max-width: 768px) {{
            .header {{ padding: 20px; flex-direction: column; gap: 15px; }}
            .container {{ padding: 10px; }}
            .player-card, .info-card {{ padding: 15px; border-radius: 16px; }}
        }}
    </style>
</head>
<body>

    <div class="header">
        <div class="brand">
            <div class="brand-icon"><i class="fas fa-play"></i></div>
            CineSearch
        </div>
        <div class="header-actions">
            <div class="badge-secure">
                <i class="fas fa-shield-alt"></i> Secure Stream
            </div>
            <a href="https://t.me/MoviiWrld" target="_blank" class="btn-join">
                <i class="fab fa-telegram-plane"></i> Join Channel
            </a>
        </div>
    </div>

    <div class="container">
        
        <div class="player-card">
            <div class="player-header">
                <div class="status-indicator">
                    <div class="status-dot"></div>
                    LIVE STREAM
                </div>
            </div>
            
            <div class="video-wrapper">
                <video id="player" poster="/thumb/{file_id}" playsinline controls>
                    <source src="/watch/{file_id}/{filename}" type="video/mp4" />
                </video>
            </div>
        </div>

        <div class="info-card">
            <div class="file-info">
                <div class="file-id">ID: {file_id[:12]}...</div>
                <div class="file-name">{filename}</div>
            </div>
            
            <div class="tags">
                <div class="tag"><i class="fas fa-bolt"></i> Direct Stream</div>
                <div class="tag"><i class="fas fa-lock"></i> Encrypted</div>
                <div class="tag"><i class="fas fa-clock"></i> No Buffering</div>
            </div>
            
            <a href="/watch/{file_id}/{filename}" download="{filename}" class="btn-download">
                <i class="fas fa-download"></i> Download File
            </a>
            
            <p style="text-align: center; font-size: 12px; color: var(--text-muted); margin-top: 5px;">
                No Audio? Watch in external player:
            </p>
            
            <div class="external-players">
                <button onclick="playInMX()" class="btn-external">
                    <i class="fas fa-mobile-alt" style="color: #2196F3;"></i>
                    MX Player
                </button>
                <button onclick="playInVLC()" class="btn-external">
                    <i class="fas fa-traffic-cone" style="color: #FF9800;"></i>
                    VLC Player
                </button>
            </div>
        </div>

    </div>
    </div>

    <script src="https://cdn.plyr.io/3.7.8/plyr.js"></script>
    <script>
        document.addEventListener('DOMContentLoaded', () => {{
            const player = new Plyr('#player', {{
                controls: ['play-large', 'play', 'progress', 'current-time', 'duration', 'mute', 'volume', 'captions', 'settings', 'pip', 'airplay', 'fullscreen'],
                settings: ['captions', 'quality', 'speed'],
                ratio: '16:9'
            }});
        }});
        function getStreamUrl() {{
            return window.location.origin + "/watch/{file_id}/{filename}";
        }}
        
        function playInMX() {{
            const url = getStreamUrl().replace(/^https?:\/\//, '');
            window.location.href = `intent://${{url}}#Intent;package=com.mxtech.videoplayer.ad;S.title={filename};end`;
        }}
        
        function playInVLC() {{
            const url = getStreamUrl();
            window.location.href = `vlc://${{url}}`;
        }}
    </script>
</body>
</html>
"""
        headers = {
            'Cross-Origin-Opener-Policy': 'same-origin',
            'Cross-Origin-Embedder-Policy': 'require-corp'
        }
        return web.Response(text=html_content, content_type='text/html', headers=headers)

    async def stream_handler(self, request):
        file_id = request.match_info['file_id']
        filename = request.match_info['filename']
        
        try:
            # 1. Look up the movie in MongoDB to get source_chat_id and source_message_id
            movie = await movies_col.find_one({'file_id': file_id})
            if not movie:
                return web.Response(status=404, text="Movie not found in database")
                
            # 2. Extract file_size from DB (if we start saving it), or fallback to chunked stream
            file_size = movie.get('file_size')
            
            # We don't need to fetch the message via get_messages! 
            # Pyrogram can stream directly from the file_id string!
            # This completely bypasses the "Peer id invalid" error for private channels!
            
            # 3. Handle Range Requests
            range_header = request.headers.get('Range', 0)
            
            if range_header and file_size:
                match = re.search(r'bytes=(\d+)-(\d*)', range_header)
                if match:
                    offset = int(match.group(1))
                    end = int(match.group(2)) if match.group(2) else file_size - 1
                else:
                    offset = 0
                    end = file_size - 1
            else:
                offset = 0
                end = file_size - 1 if file_size else None
                
            length = (end - offset + 1) if end else 0
            
            # For direct stream links, assume MP4 to trigger hardware decoders
            mime_type = 'video/mp4'
                
            headers = {
                'Content-Type': mime_type,
                'Accept-Ranges': 'bytes',
                'Content-Disposition': f'inline; filename="{filename}"',
                'Cross-Origin-Resource-Policy': 'cross-origin'
            }
            
            if file_size:
                headers['Content-Range'] = f'bytes {offset}-{end}/{file_size}'
                headers['Content-Length'] = str(length)
            
            response = web.StreamResponse(
                status=206 if (range_header and file_size) else 200,
                headers=headers
            )
            await response.prepare(request)
            
            # Pyrogram's stream_media uses chunk offsets, typically 1MB per chunk
            chunk_size = 1024 * 1024
            chunk_index = offset // chunk_size
            skip_bytes = offset % chunk_size
            bytes_left = length
            
            # Stream from Pyrogram starting at the precise chunk index
            async for chunk in self.client.stream_media(file_id, offset=chunk_index):
                if skip_bytes > 0:
                    chunk = chunk[skip_bytes:]
                    skip_bytes = 0
                    
                if bytes_left <= len(chunk):
                    try:
                        await response.write(chunk[:bytes_left])
                    except Exception:
                        pass
                    break
                    
                try:
                    await response.write(chunk)
                except Exception:
                    # Client disconnected
                    break
                    
                bytes_left -= len(chunk)
                
            return response
            
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            logger.error(f"Stream Error:\n{tb}")
            return web.Response(status=500, text=f"Streaming Failed!\n\nReason: {e}\n\nTraceback:\n{tb}")


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
