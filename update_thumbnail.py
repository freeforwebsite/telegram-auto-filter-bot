import re

with open('stream_server/server.py', 'r', encoding='utf-8') as f:
    code = f.read()

# We need to replace the entire thumb_handler method
new_thumb_method = """
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
                name = re.sub(r'\\.(mkv|mp4|avi|webm)$', '', filename, flags=re.IGNORECASE)
                tags = [r'1080p', r'720p', r'480p', r'2160p', r'4k', r'x264', r'x265', r'hevc', r'avc', r'10bit', r'hdr', r'webrip', r'web-dl', r'hdrip', r'bluray', r'brrip', r'dvdrip', r'hdtv', r'web', r'dl', r'tamil', r'telugu', r'hindi', r'malayalam', r'kannada', r'english', r'multi', r'audio', r'dual', r'sub', r'esub', r'msub', r'untouched', r'esubs', r'hq', r'line', r'predvd', r'nf', r'ta', r'\\[.*?\\]', r'\\(.*?\\)']
                for tag in tags: name = re.sub(tag, '', name, flags=re.IGNORECASE)
                name = re.sub(r'[\\._\\-]', ' ', name)
                name = re.sub(r'\\s+', ' ', name).strip()
                name = re.sub(r'@\\w+', '', name)
                name = re.sub(r't me.*', '', name, flags=re.IGNORECASE)
                return name.strip()
                
            clean_name = clean_title(movie.get('file_name', ''))
            
            if clean_name:
                omdb_api_key = os.environ.get("OMDB_API_KEY", "3bc5f75d")
                search_url = f"http://www.omdbapi.com/?apikey={omdb_api_key}&t={clean_name}"
                
                async with aiohttp.ClientSession() as session:
                    async with session.get(search_url) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            if data.get('Response') == 'True':
                                poster_url = data.get('Poster')
                                if poster_url and poster_url != "N/A":
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
                transparent_gif = b'\\x47\\x49\\x46\\x38\\x39\\x61\\x01\\x00\\x01\\x00\\x80\\x00\\x00\\xff\\xff\\xff\\x00\\x00\\x00\\x21\\xf9\\x04\\x01\\x00\\x00\\x00\\x00\\x2c\\x00\\x00\\x00\\x00\\x01\\x00\\x01\\x00\\x00\\x02\\x02\\x44\\x01\\x00\\x3b'
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
"""

# Regex to replace the old thumb_handler
old_handler_pattern = r'    async def thumb_handler\(self, request\):.*?        except Exception as e:\n            logger\.error\(f"Thumb Error: \{e\}"\)\n            return web\.Response\(status=500\)'

code = re.sub(old_handler_pattern, new_thumb_method.strip('\n'), code, flags=re.DOTALL)

with open('stream_server/server.py', 'w', encoding='utf-8') as f:
    f.write(code)
