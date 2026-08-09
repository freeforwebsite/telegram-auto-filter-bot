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

# Initialize Pyrogram Client for Streaming
stream_client = Client(
    "stream_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    in_memory=True
)

class StreamServer:
    def __init__(self, client: Client):
        self.client = client
        self.app = web.Application()
        self.app.router.add_get('/', self.health_check)
        self.app.router.add_get('/watch/{file_id}/{filename}', self.stream_handler)
        self.app.router.add_get('/player/{file_id}/{filename}', self.player_page)

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
            <link rel="stylesheet" href="https://cdn.plyr.io/3.7.8/plyr.css" />
            <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;600;800&display=swap" rel="stylesheet">
            <style>
                body {{
                    margin: 0;
                    padding: 0;
                    background: linear-gradient(135deg, #09090e 0%, #171124 50%, #0d1222 100%);
                    color: white;
                    font-family: 'Outfit', sans-serif;
                    display: flex;
                    flex-direction: column;
                    align-items: center;
                    justify-content: center;
                    min-height: 100vh;
                    overflow-x: hidden;
                }}
                /* Ambient Background Blobs */
                .blob {{
                    position: absolute;
                    filter: blur(80px);
                    z-index: -1;
                    opacity: 0.6;
                }}
                .blob-1 {{
                    top: -10%; left: -10%;
                    width: 400px; height: 400px;
                    background: #ff416c;
                    animation: float 10s infinite alternate;
                }}
                .blob-2 {{
                    bottom: -10%; right: -10%;
                    width: 500px; height: 500px;
                    background: #4facfe;
                    animation: float 12s infinite alternate-reverse;
                }}
                @keyframes float {{
                    0% {{ transform: translate(0, 0); }}
                    100% {{ transform: translate(50px, 50px); }}
                }}

                .player-container {{
                    width: 95%;
                    max-width: 1000px;
                    border-radius: 20px;
                    overflow: hidden;
                    /* Glassmorphism */
                    background: rgba(25, 25, 35, 0.4);
                    backdrop-filter: blur(20px);
                    -webkit-backdrop-filter: blur(20px);
                    border: 1px solid rgba(255, 255, 255, 0.1);
                    box-shadow: 0 25px 50px rgba(0, 0, 0, 0.5);
                    padding: 20px;
                    margin: 20px 0;
                }}
                .header {{
                    text-align: center;
                    margin-bottom: 20px;
                }}
                .header h1 {{
                    margin: 0;
                    font-size: 2.2rem;
                    font-weight: 800;
                    background: linear-gradient(90deg, #ff416c 0%, #ff4b2b 100%);
                    -webkit-background-clip: text;
                    -webkit-text-fill-color: transparent;
                    letter-spacing: 1px;
                }}
                .header p {{
                    margin: 5px 0 0 0;
                    font-size: 0.95rem;
                    color: rgba(255,255,255,0.6);
                    white-space: nowrap;
                    overflow: hidden;
                    text-overflow: ellipsis;
                }}
                .video-wrapper {{
                    border-radius: 12px;
                    overflow: hidden;
                    box-shadow: 0 10px 30px rgba(0,0,0,0.5);
                    background: #000;
                }}
                /* Custom Plyr Theme */
                :root {{
                    --plyr-color-main: #ff416c;
                    --plyr-video-background: transparent;
                }}
                
                .buttons-container {{
                    display: flex;
                    justify-content: center;
                    gap: 20px;
                    margin-top: 25px;
                    flex-wrap: wrap;
                }}
                .btn {{
                    padding: 12px 30px;
                    border-radius: 50px;
                    text-decoration: none;
                    color: white;
                    font-weight: 600;
                    font-size: 1rem;
                    transition: all 0.3s ease;
                    display: flex;
                    align-items: center;
                    gap: 10px;
                    border: 1px solid rgba(255,255,255,0.1);
                }}
                .btn-primary {{
                    background: linear-gradient(90deg, #ff416c 0%, #ff4b2b 100%);
                    box-shadow: 0 10px 20px rgba(255, 65, 108, 0.3);
                    border: none;
                }}
                .btn-primary:hover {{
                    transform: translateY(-3px);
                    box-shadow: 0 15px 25px rgba(255, 65, 108, 0.5);
                }}
                .btn-secondary {{
                    background: rgba(255, 255, 255, 0.05);
                    backdrop-filter: blur(10px);
                }}
                .btn-secondary:hover {{
                    background: rgba(255, 255, 255, 0.15);
                    transform: translateY(-3px);
                }}
            </style>
        </head>
        <body>
            <div class="blob blob-1"></div>
            <div class="blob blob-2"></div>
            
            <div class="player-container">
                <div class="header">
                    <h1>CineSearch Player</h1>
                    <p>{filename}</p>
                </div>
                
                <div class="video-wrapper">
                    <video id="player" playsinline controls>
                        <source src="/watch/{file_id}/{filename}" type="video/mp4" />
                    </video>
                </div>
                
                <div class="buttons-container">
                    <a href="https://t.me/MoviiWrld" class="btn btn-primary">
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z"/></svg>
                        Join Channel
                    </a>
                    <a href="/watch/{file_id}/{filename}" download="{filename}" class="btn btn-secondary">
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/></svg>
                        Download Now
                    </a>
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
            
            # 2. Fetch the message using Pyrogram to get the exact file_size
            msg = await self.client.get_messages(source_chat_id, source_message_id)
            if not msg:
                return web.Response(status=404, text="Original message not found in Telegram")
                
            media = msg.document or msg.video
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
            
            headers = {
                'Content-Type': 'video/mp4',
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
            
            # Stream from Pyrogram
            async for chunk in self.client.stream_media(file_id, limit=length, offset=offset):
                await response.write(chunk)
                
            return response
            
        except Exception as e:
            logger.error(f"Stream Error: {{e}}")
            return web.Response(status=500, text="Streaming Failed")

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
