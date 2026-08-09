import re

with open('stream_server/server.py', 'r', encoding='utf-8') as f:
    code = f.read()

# 1. Add the route
code = code.replace("self.app.router.add_get('/player/{file_id}/{filename}', self.player_page)",
                    "self.app.router.add_get('/player/{file_id}/{filename}', self.player_page)\n        self.app.router.add_get('/thumb/{file_id}', self.thumb_handler)")

# 2. Add the poster attribute to the video tag
code = code.replace("<video id=\"player\" playsinline controls>",
                    "<video id=\"player\" poster=\"/thumb/{file_id}\" playsinline controls>")

# 3. Add the thumb_handler method
thumb_method = """
    async def thumb_handler(self, request):
        file_id = request.match_info['file_id']
        try:
            movie = await movies_col.find_one({'file_id': file_id})
            if not movie:
                return web.Response(status=404)
                
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
                # Return a transparent 1x1 pixel if no thumb
                transparent_gif = b'\\x47\\x49\\x46\\x38\\x39\\x61\\x01\\x00\\x01\\x00\\x80\\x00\\x00\\xff\\xff\\xff\\x00\\x00\\x00\\x21\\xf9\\x04\\x01\\x00\\x00\\x00\\x00\\x2c\\x00\\x00\\x00\\x00\\x01\\x00\\x01\\x00\\x00\\x02\\x02\\x44\\x01\\x00\\x3b'
                return web.Response(body=transparent_gif, content_type='image/gif')
                
            # Get the largest thumbnail
            thumb = media.thumbs[-1]
            thumb_file_id = thumb.file_id
            
            # Download thumbnail to memory
            thumb_bytes = await self.client.download_media(thumb_file_id, in_memory=True)
            if not thumb_bytes:
                return web.Response(status=404)
                
            return web.Response(body=thumb_bytes.getvalue(), content_type='image/jpeg')
        except Exception as e:
            logger.error(f"Thumb Error: {e}")
            return web.Response(status=500)

async def start_stream_server():"""

code = code.replace("async def start_stream_server():", thumb_method)

with open('stream_server/server.py', 'w', encoding='utf-8') as f:
    f.write(code)
