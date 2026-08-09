import os
import re
import math
import logging
from aiohttp import web
from pyrogram import Client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

API_ID = os.environ.get('API_ID')
API_HASH = os.environ.get('API_HASH')
BOT_TOKEN = os.environ.get('BOT_TOKEN')
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
            <style>
                body {{
                    margin: 0;
                    padding: 0;
                    background-color: #0f111a;
                    color: white;
                    font-family: 'Inter', sans-serif;
                    display: flex;
                    flex-direction: column;
                    align-items: center;
                    justify-content: center;
                    height: 100vh;
                }}
                .player-container {{
                    width: 90%;
                    max-width: 1000px;
                    border-radius: 12px;
                    overflow: hidden;
                    box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5);
                    background: #1a1d2d;
                }}
                video {{
                    width: 100%;
                    height: auto;
                    display: block;
                }}
                .header {{
                    padding: 20px;
                    text-align: center;
                    background: linear-gradient(90deg, #ff416c 0%, #ff4b2b 100%);
                    font-weight: bold;
                    font-size: 1.2rem;
                }}
                .buttons {{
                    display: flex;
                    justify-content: center;
                    gap: 15px;
                    padding: 20px;
                }}
                .btn {{
                    padding: 10px 20px;
                    border-radius: 8px;
                    text-decoration: none;
                    color: white;
                    font-weight: bold;
                    background: #2b2e4a;
                    transition: 0.3s;
                }}
                .btn:hover {{
                    background: #ff4b2b;
                }}
            </style>
        </head>
        <body>
            <div class="player-container">
                <div class="header">CineSearch Web Player</div>
                <video controls autoplay>
                    <source src="/watch/{file_id}/{filename}" type="video/mp4">
                    Your browser does not support the video tag.
                </video>
                <div class="buttons">
                    <a href="https://t.me/MoviiWrld" class="btn">Join Channel</a>
                    <a href="/watch/{file_id}/{filename}" class="btn" download="{filename}">Download Now</a>
                </div>
            </div>
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
