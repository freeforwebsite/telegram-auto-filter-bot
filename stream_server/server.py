import os
import re
import math
import logging
import mimetypes
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
scrape_queue = db_client['cinesearch_db']['scrape_queue']
published_col = db_client['telegram_bot']['published_movies']

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
        self.app.router.add_get('/admin', self.admin_page)
        self.app.router.add_get('/api/queue/stats', self.api_stats)
        self.app.router.add_get('/api/queue/failed', self.api_failed)
        self.app.router.add_get('/api/queue/completed', self.api_completed)
        self.app.router.add_get('/api/movies', self.api_movies)
        self.app.router.add_get('/api/published', self.api_published_admin)
        self.app.router.add_post('/api/published', self.api_publish)
        self.app.router.add_post('/api/published/delete', self.api_delete_published)
        self.app.router.add_get('/api/app/movies', self.api_app_movies)
        self.app.router.add_post('/api/queue/retry', self.api_retry)
        self.app.router.add_post('/api/queue/delete', self.api_delete)
        self.app.router.add_post('/api/queue/retry_all', self.api_retry_all)
        self.app.router.add_post('/api/queue/clear_all', self.api_clear_all)
        self.app.router.add_get('/watch/{file_id}/{filename}', self.stream_handler)
        self.app.router.add_options('/watch/{file_id}/{filename}', self.options_handler)
        self.app.router.add_get('/player/{file_id}/{filename}', self.player_page)
        self.app.router.add_get('/embed/{file_id}/{filename}', self.embed_player)
        self.app.router.add_get('/thumb/{file_id}', self.thumb_handler)
        self.app.router.add_get('/admin', self.admin_page)
        self.app.router.add_static('/admin/', 'stream_server/admin')

    async def admin_page(self, request):
        import os
        index_path = os.path.join(os.path.dirname(__file__), 'admin', 'index.html')
        with open(index_path, 'r', encoding='utf-8') as f:
            return web.Response(text=f.read(), content_type='text/html')

    async def options_handler(self, request):
        headers = {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, HEAD, OPTIONS',
            'Access-Control-Allow-Headers': 'Range, Accept, Content-Type'
        }
        return web.Response(status=204, headers=headers)

    def check_admin(self, request):
        if request.cookies.get('admin_pwd') != 'admin123':
            return False
        return True

    async def admin_page(self, request):
        try:
            with open(os.path.join(os.path.dirname(__file__), 'admin.html'), 'r') as f:
                return web.Response(text=f.read(), content_type='text/html')
        except Exception as e:
            return web.Response(text=str(e), status=500)

    async def api_stats(self, request):
        if not self.check_admin(request): return web.Response(status=401)
        pending = await scrape_queue.count_documents({'status': 'pending'})
        completed = await scrape_queue.count_documents({'status': 'completed'})
        failed = await scrape_queue.count_documents({'status': 'failed'})
        db_total = await movies_col.count_documents({})
        return web.json_response({'pending': pending, 'completed': completed, 'failed': failed, 'db_total': db_total})

    async def api_failed(self, request):
        if not self.check_admin(request): return web.Response(status=401)
        cursor = scrape_queue.find({'status': 'failed'}).sort('added_on', -1).limit(500)
        failed = []
        async for doc in cursor:
            doc['_id'] = str(doc['_id'])
            doc['added_on'] = doc.get('added_on', '').isoformat() if hasattr(doc.get('added_on'), 'isoformat') else str(doc.get('added_on', ''))
            failed.append(doc)
        return web.json_response(failed)

    async def api_completed(self, request):
        if not self.check_admin(request): return web.Response(status=401)
        cursor = scrape_queue.find({'status': 'completed'}).sort('added_on', -1).limit(500)
        completed = []
        async for doc in cursor:
            doc['_id'] = str(doc['_id'])
            doc['added_on'] = doc.get('added_on', '').isoformat() if hasattr(doc.get('added_on'), 'isoformat') else str(doc.get('added_on', ''))
            completed.append(doc)
        return web.json_response(completed)

    async def api_movies(self, request):
        if not self.check_admin(request): return web.Response(status=401)
        try:
            page = int(request.query.get('page', 1))
            search_query = request.query.get('search', '').strip()
            limit = 50
            skip = (page - 1) * limit
            
            query = {}
            if search_query:
                import re
                query = {"$or": [{"file_name": {"$regex": re.escape(search_query), "$options": "i"}}, {"caption": {"$regex": re.escape(search_query), "$options": "i"}}]}
                
            cursor = movies_col.find(query).sort('_id', -1).skip(skip).limit(limit)
            movies = []
            async for doc in cursor:
                doc['_id'] = str(doc['_id'])
                movies.append(doc)
            return web.json_response(movies)
        except Exception as e:
            return web.Response(status=500, text=str(e))
        

    async def api_published_admin(self, request):
        if not self.check_admin(request): return web.Response(status=401)
        cursor = published_col.find({}).sort('_id', -1)
        movies = []
        async for doc in cursor:
            doc['_id'] = str(doc['_id'])
            movies.append(doc)
        return web.json_response(movies)

    async def api_publish(self, request):
        if not self.check_admin(request): return web.Response(status=401)
        data = await request.json()
        
        movie_doc = {
            "title": data.get("title"),
            "description": data.get("description", ""),
            "poster": data.get("poster", ""),
            "backdrop": data.get("backdrop", ""),
            "category": data.get("category", "All"),
            "links": data.get("links", []) # [{"quality": "1080p", "file_id": "..."}]
        }
        
        if data.get("id"):
            from bson.objectid import ObjectId
            await published_col.update_one({"_id": ObjectId(data["id"])}, {"$set": movie_doc})
        else:
            await published_col.insert_one(movie_doc)
            
        return web.Response(text='OK')

    async def api_delete_published(self, request):
        if not self.check_admin(request): return web.Response(status=401)
        data = await request.json()
        from bson.objectid import ObjectId
        await published_col.delete_one({'_id': ObjectId(data['id'])})
        return web.Response(text='OK')

    # PUBLIC ROUTE FOR THE CONSUMER APP
    async def api_app_movies(self, request):
        # Allow CORS for the app
        headers = {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, OPTIONS",
        }
        cursor = published_col.find({}).sort('_id', -1)
        movies = []
        async for doc in cursor:
            doc['_id'] = str(doc['_id'])
            movies.append(doc)
        return web.json_response(movies, headers=headers)

    async def api_retry(self, request):
        if not self.check_admin(request): return web.Response(status=401)
        data = await request.json()
        from bson.objectid import ObjectId
        await scrape_queue.update_one({'_id': ObjectId(data['id'])}, {'$set': {'status': 'pending'}})
        return web.Response(text='OK')

    async def api_delete(self, request):
        if not self.check_admin(request): return web.Response(status=401)
        data = await request.json()
        from bson.objectid import ObjectId
        await scrape_queue.delete_one({'_id': ObjectId(data['id'])})
        return web.Response(text='OK')

    async def api_retry_all(self, request):
        if not self.check_admin(request): return web.Response(status=401)
        await scrape_queue.update_many({'status': 'failed'}, {'$set': {'status': 'pending'}})
        return web.Response(text='OK')

    async def api_clear_all(self, request):
        if not self.check_admin(request): return web.Response(status=401)
        await scrape_queue.delete_many({'status': 'failed'})
        return web.Response(text='OK')

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
<title>LoveToRide · {filename}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Nunito:wght@400;500;600;700;800;900&family=Poppins:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css">
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
html{{scroll-behavior:smooth}}
:root{{
--bg:#0B0F1E;
--card:#131929;
--card2:#1A2238;
--card3:#1F2940;
--purple:#7B5CF5;
--purple2:#9B7DFF;
--pink:#F0507E;
--pink2:#FF6B9D;
--blue:#4E9BFF;
--blue2:#72B4FF;
--teal:#00D4AA;
--teal2:#00F5C4;
--orange:#FF8C42;
--yellow:#FFD166;
--white:#FFFFFF;
--text:#E8EEFF;
--text2:#9BA3BC;
--text3:#6B7490;
--border:rgba(255,255,255,0.07);
--border2:rgba(255,255,255,0.12);
--glow-purple:rgba(123,92,245,0.4);
--glow-pink:rgba(240,80,126,0.4);
--glow-teal:rgba(0,212,170,0.3);
}}
body{{
font-family:'Nunito',sans-serif;
background:var(--bg);
color:var(--text);
min-height:100vh;
overflow-x:hidden;
}}
/* ─── ANIMATED BG ─── */
.bg-wrap{{position:fixed;inset:0;z-index:0;overflow:hidden;pointer-events:none}}
.bg-glow{{
position:absolute;border-radius:50%;filter:blur(120px);opacity:.25;
animation:bgFloat 15s ease-in-out infinite alternate;
}}
.bg-glow.g1{{width:700px;height:700px;background:var(--purple);top:-200px;left:-200px;animation-duration:18s}}
.bg-glow.g2{{width:600px;height:600px;background:var(--pink);bottom:-150px;right:-100px;animation-duration:22s;animation-direction:alternate-reverse}}
.bg-glow.g3{{width:400px;height:400px;background:var(--blue);top:40%;left:50%;animation-duration:14s}}
@keyframes bgFloat{{
0%{{transform:translate(0,0) scale(1)}}
100%{{transform:translate(50px,-50px) scale(1.15)}}
}}
/* Subtle grid */
.bg-grid{{
position:absolute;inset:0;
background-image:linear-gradient(rgba(255,255,255,.025) 1px,transparent 1px),
linear-gradient(90deg,rgba(255,255,255,.025) 1px,transparent 1px);
background-size:40px 40px;
}}
/* ─── LAYOUT ─── */
.page{{position:relative;z-index:1;max-width:960px;margin:0 auto;padding:0 16px 60px}}
/* ─── NAVBAR ─── */
nav{{
display:flex;align-items:center;justify-content:space-between;
padding:18px 0 16px;
border-bottom:1px solid var(--border);
margin-bottom:32px;
}}
.nav-logo{{
display:flex;align-items:center;gap:10px;
}}
.logo-icon{{
width:38px;height:38px;border-radius:12px;
background:linear-gradient(135deg,var(--purple),var(--pink));
display:flex;align-items:center;justify-content:center;
font-size:18px;
box-shadow:0 4px 20px var(--glow-purple);
}}
.logo-name{{
font-family:'Poppins',sans-serif;
font-size:20px;font-weight:800;letter-spacing:-.5px;
}}
.logo-name b{{
background:linear-gradient(90deg,var(--purple2),var(--pink2));
-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;
}}
.nav-right{{display:flex;align-items:center;gap:10px}}
.nav-badge{{
display:flex;align-items:center;gap:6px;
font-size:12px;font-weight:700;
padding:7px 14px;border-radius:20px;
background:rgba(0,212,170,.1);
border:1px solid rgba(0,212,170,.25);
color:var(--teal2);
}}
.nav-badge i{{font-size:10px;animation:pulse 2s infinite}}
@keyframes pulse{{0%,100%{{opacity:1}}50%{{opacity:.4}}}}
.btn-tg-nav{{
display:flex;align-items:center;gap:7px;
font-size:13px;font-weight:700;
padding:9px 18px;border-radius:20px;
background:linear-gradient(135deg,var(--purple),var(--pink));
color:#fff;text-decoration:none;
box-shadow:0 4px 20px var(--glow-purple);
transition:all .25s;border:none;cursor:pointer;
}}
.btn-tg-nav:hover{{transform:translateY(-2px);box-shadow:0 8px 30px var(--glow-purple)}}
/* ─── COUNTDOWN ─── */
#cd-section{{
display:flex;flex-direction:column;align-items:center;
padding:40px 0 60px;
animation:fadeUp .6s ease both;
}}
@keyframes fadeUp{{from{{opacity:0;transform:translateY(24px)}}to{{opacity:1;transform:translateY(0)}}}}
/* Circular progress timer */
.timer-wrap{{
position:relative;width:180px;height:180px;
margin-bottom:36px;
}}
.timer-svg{{width:100%;height:100%;transform:rotate(-90deg)}}
.t-track{{fill:none;stroke:rgba(255,255,255,.06);stroke-width:6}}
.t-prog{{
fill:none;stroke-width:6;stroke-linecap:round;
stroke:url(#tg);
stroke-dasharray:502;stroke-dashoffset:502;
transition:stroke-dashoffset .12s linear;
filter:drop-shadow(0 0 8px rgba(123,92,245,.8));
}}
.timer-inner{{
position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;
gap:2px;
}}
.timer-num{{
font-family:'Poppins',sans-serif;
font-size:56px;font-weight:900;line-height:1;letter-spacing:-3px;
background:linear-gradient(160deg,var(--white),var(--purple2),var(--pink2));
-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;
}}
.timer-label{{font-size:10px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:var(--text3)}}
/* Orbit dot */
.t-orbit{{position:absolute;inset:-4px;border-radius:50%;animation:orb 1.1s linear infinite}}
.t-orbit::before{{
content:'';position:absolute;top:8px;left:50%;transform:translateX(-50%);
width:10px;height:10px;border-radius:50%;
background:var(--pink2);
box-shadow:0 0 14px var(--pink),0 0 28px var(--glow-pink);
}}
@keyframes orb{{to{{transform:rotate(360deg)}}}}
.cd-title{{
font-family:'Poppins',sans-serif;
font-size:26px;font-weight:800;letter-spacing:-.5px;
text-align:center;margin-bottom:8px;
}}
.cd-title span{{
background:linear-gradient(90deg,var(--purple2),var(--pink2),var(--blue2));
-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;
}}
.cd-sub{{font-size:14px;color:var(--text2);text-align:center;margin-bottom:32px;font-weight:500}}
/* Steps — pill row */
.cd-steps{{
display:flex;align-items:center;gap:8px;
background:var(--card);
border:1px solid var(--border);
border-radius:20px;padding:6px;
}}
.cd-step{{
display:flex;align-items:center;gap:8px;
padding:10px 20px;border-radius:16px;
font-size:12px;font-weight:700;letter-spacing:.3px;
color:var(--text3);transition:all .4s cubic-bezier(.16,1,.3,1);
}}
.cd-step i{{font-size:11px}}
.cd-step.on{{
background:linear-gradient(135deg,var(--purple),var(--pink));
color:#fff;
box-shadow:0 4px 20px var(--glow-purple);
}}
.cd-step.ok{{color:var(--teal2);background:rgba(0,212,170,.1)}}
.step-arrow{{color:var(--text3);font-size:10px}}
/* ─── PLAYER SECTION ─── */
#ps{{display:none}}
#ps.show{{display:block;animation:fadeUp .6s ease both}}
/* ─── VIDEO PLAYER ─── */
.video-section{{
background:var(--card);
border-radius:24px;
overflow:hidden;
border:1px solid var(--border);
box-shadow:0 24px 80px rgba(0,0,0,.6),0 0 0 1px rgba(255,255,255,.04);
margin-bottom:20px;
}}
.video-top-bar{{
display:flex;align-items:center;justify-content:space-between;
padding:14px 18px;
border-bottom:1px solid var(--border);
}}
.vtb-left{{display:flex;align-items:center;gap:10px}}
.live-dot{{
display:flex;align-items:center;gap:6px;
background:rgba(0,212,170,.12);
border:1px solid rgba(0,212,170,.3);
padding:5px 12px;border-radius:20px;
font-size:11px;font-weight:700;color:var(--teal2);letter-spacing:.5px;
}}
.live-dot::before{{
content:'';width:6px;height:6px;border-radius:50%;
background:var(--teal2);animation:pulse 1.5s infinite;
box-shadow:0 0 8px var(--teal);
}}
.vtb-right{{display:flex;align-items:center;gap:8px}}
.icon-btn{{
width:34px;height:34px;border-radius:10px;border:none;cursor:pointer;
background:rgba(255,255,255,.06);color:var(--text2);
display:flex;align-items:center;justify-content:center;font-size:13px;
transition:all .2s;
}}
.icon-btn:hover{{background:rgba(255,255,255,.12);color:#fff}}
/* Video frame */
.vid-frame{{
position:relative;background:#000;
}}
.vid-frame::before{{
content:'';position:absolute;top:0;left:0;right:0;height:2px;z-index:10;
background:linear-gradient(90deg,var(--purple),var(--pink),var(--blue),var(--teal));
background-size:300% 100%;animation:rainbowSlide 3s linear infinite;
}}
@keyframes rainbowSlide{{0%{{background-position:0% 0}}100%{{background-position:300% 0}}}}
#vid{{display:block;width:100%;aspect-ratio:16/9;background:#000;cursor:pointer}}
/* Buffer overlay */
.vbuf{{
position:absolute;inset:0;display:none;
align-items:center;justify-content:center;
background:rgba(11,15,30,.7);backdrop-filter:blur(4px);
}}
.vbuf.on{{display:flex}}
.buf-spin{{
width:50px;height:50px;border-radius:50%;
border:3px solid rgba(123,92,245,.2);
border-top-color:var(--purple2);
border-right-color:var(--pink2);
animation:spin .7s linear infinite;
}}
@keyframes spin{{to{{transform:rotate(360deg)}}}}
/* Center pop */
.cpop-w{{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;pointer-events:none}}
.cpop-ico{{
width:72px;height:72px;border-radius:50%;
background:linear-gradient(135deg,rgba(123,92,245,.4),rgba(240,80,126,.4));
backdrop-filter:blur(8px);border:1.5px solid rgba(255,255,255,.25);
display:flex;align-items:center;justify-content:center;
font-size:24px;color:#fff;opacity:0;
}}
.cpop-ico.go{{animation:cpAnim .55s forwards}}
@keyframes cpAnim{{
0%{{opacity:1;transform:scale(.8)}}
55%{{opacity:1;transform:scale(1.1)}}
100%{{opacity:0;transform:scale(1.4)}}
}}
/* ─── CONTROL BAR ─── */
.ctrl{{
position:absolute;bottom:0;left:0;right:0;
background:linear-gradient(transparent,rgba(11,15,30,.98));
padding:52px 18px 14px;
transition:opacity .3s;
}}
.vid-frame.hc .ctrl{{opacity:0;pointer-events:none}}
.vid-frame.hc{{cursor:none}}
/* Seekbar */
.seekbar{{
position:relative;height:4px;background:rgba(255,255,255,.1);
border-radius:10px;cursor:pointer;margin-bottom:14px;transition:height .15s;
}}
.seekbar:hover{{height:6px}}
.sb-buf,.sb-p{{position:absolute;inset:0;height:100%;border-radius:10px}}
.sb-buf{{background:rgba(255,255,255,.15)}}
.sb-p{{
background:linear-gradient(90deg,var(--purple),var(--pink),var(--blue));
width:0%;transition:width .1s linear;
box-shadow:0 0 10px rgba(123,92,245,.6);
}}
.sb-thumb{{
position:absolute;top:50%;width:14px;height:14px;border-radius:50%;
background:#fff;box-shadow:0 0 10px var(--purple2),0 0 20px var(--glow-purple);
transform:translate(-50%,-50%) scale(0);transition:transform .15s;pointer-events:none;
}}
.seekbar:hover .sb-thumb{{transform:translate(-50%,-50%) scale(1)}}
.sb-tip{{
position:absolute;bottom:18px;transform:translateX(-50%);
background:var(--card2);border:1px solid var(--border2);
color:var(--text);font-size:11px;font-weight:700;
padding:4px 10px;border-radius:8px;pointer-events:none;
white-space:nowrap;opacity:0;transition:opacity .15s;
box-shadow:0 4px 16px rgba(0,0,0,.5);
}}
.seekbar:hover .sb-tip{{opacity:1}}
/* Control buttons */
.ctrl-row{{display:flex;align-items:center;gap:2px}}
.cb{{
background:none;border:none;color:rgba(255,255,255,.55);
cursor:pointer;padding:7px 9px;border-radius:10px;font-size:14px;
transition:all .2s;display:flex;align-items:center;gap:4px;
}}
.cb:hover{{background:rgba(255,255,255,.1);color:#fff}}
#pbtn{{font-size:19px}}
.t-disp{{
font-size:12px;font-weight:700;color:rgba(255,255,255,.5);
padding:0 8px;white-space:nowrap;letter-spacing:.3px;
}}
.vol-g{{display:flex;align-items:center;gap:6px}}
.vol-r{{
-webkit-appearance:none;appearance:none;
width:72px;height:4px;border-radius:4px;
background:rgba(255,255,255,.18);outline:none;cursor:pointer;
}}
.vol-r::-webkit-slider-thumb{{
-webkit-appearance:none;width:13px;height:13px;
border-radius:50%;background:#fff;cursor:pointer;
box-shadow:0 0 8px var(--purple2);
}}
.spop{{
position:absolute;bottom:58px;right:0;
background:var(--card2);border:1px solid var(--border2);
border-radius:14px;display:none;z-index:30;min-width:120px;
box-shadow:0 20px 60px rgba(0,0,0,.8);overflow:hidden;
}}
.spop.on{{display:block}}
.si{{
padding:10px 18px;font-size:13px;font-weight:600;
cursor:pointer;color:var(--text2);transition:all .15s;
}}
.si:hover,.si.sel{{background:rgba(123,92,245,.15);color:var(--purple2)}}
/* ─── INFO CARD BELOW PLAYER ─── */
.info-card{{
display:flex;flex-wrap:wrap;gap:16px;align-items:center;
background:var(--card);border:1px solid var(--border);
border-radius:20px;padding:18px 22px;
margin-bottom:20px;
box-shadow:0 8px 40px rgba(0,0,0,.3);
}}
.info-left{{flex:1;min-width:0}}
.info-fname{{
font-family:'Poppins',sans-serif;
font-size:16px;font-weight:700;letter-spacing:-.3px;
color:#fff;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
margin-bottom:8px;
}}
.info-tags{{display:flex;flex-wrap:wrap;gap:8px}}
.tag{{
display:flex;align-items:center;gap:5px;
font-size:11px;font-weight:700;letter-spacing:.3px;
padding:5px 12px;border-radius:20px;
}}
.tag-purple{{background:rgba(123,92,245,.15);color:var(--purple2);border:1px solid rgba(123,92,245,.25)}}
.tag-teal{{background:rgba(0,212,170,.12);color:var(--teal2);border:1px solid rgba(0,212,170,.25)}}
.tag-blue{{background:rgba(78,155,255,.12);color:var(--blue2);border:1px solid rgba(78,155,255,.25)}}
/* Download button */
.btn-download{{
display:flex;align-items:center;gap:10px;
padding:13px 26px;border-radius:16px;
font-family:'Poppins',sans-serif;
font-size:14px;font-weight:700;
color:#fff;text-decoration:none;border:none;cursor:pointer;
background:linear-gradient(135deg,var(--purple),var(--pink));
box-shadow:0 6px 28px var(--glow-purple);
transition:all .25s;position:relative;overflow:hidden;
white-space:nowrap;
}}
.btn-download::before{{
content:'';position:absolute;inset:0;
background:linear-gradient(105deg,transparent 35%,rgba(255,255,255,.2) 50%,transparent 65%);
background-size:200% 100%;animation:shimmer 2.5s ease-in-out infinite;
}}
.btn-download:hover{{transform:translateY(-3px);box-shadow:0 12px 40px var(--glow-purple)}}
@keyframes shimmer{{0%{{background-position:-200% 0}}100%{{background-position:200% 0}}}}
/* ─── EXTERNAL PLAYERS ─── */
.section-title{{
display:flex;align-items:center;gap:12px;
margin-bottom:16px;
}}
.section-title h2{{
font-family:'Poppins',sans-serif;
font-size:18px;font-weight:800;letter-spacing:-.3px;
color:#fff;
}}
.section-title .badge{{
font-size:10px;font-weight:700;letter-spacing:1px;text-transform:uppercase;
padding:4px 12px;border-radius:20px;
background:rgba(255,140,66,.15);color:var(--orange);
border:1px solid rgba(255,140,66,.3);
}}
.players-grid{{
display:grid;grid-template-columns:repeat(3,1fr);gap:14px;
margin-bottom:24px;
}}
.player-card{{
background:var(--card);border:1px solid var(--border);
border-radius:22px;padding:24px 16px 20px;
display:flex;flex-direction:column;align-items:center;gap:12px;
cursor:pointer;text-decoration:none;color:var(--text);
transition:all .3s cubic-bezier(.16,1,.3,1);
position:relative;overflow:hidden;
}}
/* Hover top shimmer */
.player-card::before{{
content:'';position:absolute;top:0;left:0;right:0;height:2px;
transform:scaleX(0);transition:transform .3s ease;
transform-origin:left;
}}
.pc-vlc::before{{background:linear-gradient(90deg,#FF8C00,#FFD166)}}
.pc-mx::before{{background:linear-gradient(90deg,#4E9BFF,#00D4AA)}}
.pc-pi::before{{background:linear-gradient(90deg,#00D4AA,#7B5CF5)}}
.player-card:hover{{
transform:translateY(-6px);
border-color:var(--border2);
box-shadow:0 20px 60px rgba(0,0,0,.5);
}}
.player-card:hover::before{{transform:scaleX(1)}}
/* App icon */
.app-icon{{
width:64px;height:64px;border-radius:20px;
display:flex;align-items:center;justify-content:center;
font-size:30px;
box-shadow:0 8px 24px rgba(0,0,0,.4);
position:relative;overflow:hidden;
}}
.app-icon::after{{
content:'';position:absolute;inset:0;
background:linear-gradient(145deg,rgba(255,255,255,.15),transparent 60%);
}}
.app-name{{
font-family:'Poppins',sans-serif;
font-size:15px;font-weight:800;letter-spacing:-.2px;color:#fff;
text-align:center;
}}
.app-feats{{
display:flex;flex-direction:column;align-items:center;gap:4px;width:100%;
}}
.app-feat{{
display:flex;align-items:center;gap:6px;
font-size:11px;font-weight:600;color:var(--text2);
}}
.app-feat i{{font-size:9px}}
.pc-vlc .app-feat i{{color:var(--orange)}}
.pc-mx .app-feat i{{color:var(--blue2)}}
.pc-pi .app-feat i{{color:var(--teal2)}}
/* Open buttons */
.btn-open{{
display:flex;align-items:center;justify-content:center;gap:8px;
width:100%;padding:11px;border-radius:14px;
font-size:13px;font-weight:800;letter-spacing:.3px;
border:none;cursor:pointer;color:#fff;
transition:all .25s;position:relative;overflow:hidden;
}}
.btn-open::before{{
content:'';position:absolute;inset:0;
background:linear-gradient(105deg,transparent 35%,rgba(255,255,255,.15) 50%,transparent 65%);
background-size:200% 100%;
}}
.btn-open:hover::before{{animation:shimmer 1.5s ease-in-out infinite}}
.pc-vlc .btn-open{{background:linear-gradient(135deg,#FF8C00,#FF6600);box-shadow:0 4px 20px rgba(255,140,0,.3)}}
.pc-mx .btn-open{{background:linear-gradient(135deg,#1976D2,#0288D1);box-shadow:0 4px 20px rgba(30,118,210,.3)}}
.pc-pi .btn-open{{background:linear-gradient(135deg,#00B894,#00D4AA);box-shadow:0 4px 20px rgba(0,212,170,.3)}}
.btn-open:hover{{transform:scale(1.02)}}
/* ─── TELEGRAM CARD ─── */
.tg-card{{
border-radius:24px;overflow:hidden;
margin-bottom:24px;
position:relative;
background:linear-gradient(135deg,rgba(123,92,245,.2),rgba(240,80,126,.15),rgba(78,155,255,.1));
border:1px solid rgba(123,92,245,.25);
box-shadow:0 16px 60px rgba(123,92,245,.15);
}}
/* Animated background pattern */
.tg-card::before{{
content:'';position:absolute;inset:0;
background:
radial-gradient(circle at 20% 50%,rgba(123,92,245,.15),transparent 50%),
radial-gradient(circle at 80% 50%,rgba(240,80,126,.12),transparent 50%);
animation:tgBg 6s ease-in-out infinite alternate;
}}
@keyframes tgBg{{
0%{{transform:scale(1)}}100%{{transform:scale(1.1)}}
}}
.tg-inner{{
position:relative;z-index:1;
padding:28px 28px;
display:flex;flex-wrap:wrap;align-items:center;gap:20px;
}}
.tg-icon-wrap{{
width:64px;height:64px;border-radius:20px;flex-shrink:0;
background:linear-gradient(135deg,var(--purple),var(--pink));
display:flex;align-items:center;justify-content:center;
font-size:28px;color:#fff;
box-shadow:0 8px 30px var(--glow-purple);
position:relative;
}}
.tg-icon-wrap::after{{
content:'';position:absolute;inset:0;border-radius:20px;
background:linear-gradient(145deg,rgba(255,255,255,.2),transparent);
}}
.tg-text{{flex:1;min-width:160px}}
.tg-label{{
font-size:11px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;
color:var(--purple2);margin-bottom:6px;
display:flex;align-items:center;gap:6px;
}}
.tg-label::before{{content:'';width:16px;height:2px;background:var(--purple2);border-radius:2px}}
.tg-name{{
font-family:'Poppins',sans-serif;
font-size:20px;font-weight:800;letter-spacing:-.5px;color:#fff;
margin-bottom:6px;
}}
.tg-desc{{font-size:13px;color:rgba(255,255,255,.6);font-weight:500;line-height:1.5}}
.btn-join{{
display:flex;align-items:center;gap:10px;
padding:14px 28px;border-radius:16px;
font-family:'Poppins',sans-serif;
font-size:14px;font-weight:800;
color:#fff;text-decoration:none;border:none;cursor:pointer;
background:linear-gradient(135deg,#229ED9,#1A7FB5);
box-shadow:0 6px 28px rgba(34,158,217,.35);
transition:all .25s;white-space:nowrap;
position:relative;overflow:hidden;
}}
.btn-join::before{{
content:'';position:absolute;inset:0;
background:linear-gradient(105deg,transparent 35%,rgba(255,255,255,.2) 50%,transparent 65%);
background-size:200% 100%;animation:shimmer 2s ease-in-out 1s infinite;
}}
.btn-join:hover{{transform:translateY(-3px);box-shadow:0 12px 40px rgba(34,158,217,.5)}}
.btn-join i{{font-size:16px}}
/* ─── STATS ROW ─── */
.stats-row{{
display:grid;grid-template-columns:repeat(4,1fr);gap:12px;
margin-bottom:24px;
}}
.stat-box{{
background:var(--card);border:1px solid var(--border);
border-radius:18px;padding:18px 14px;
text-align:center;
transition:all .25s;
}}
.stat-box:hover{{border-color:var(--border2);transform:translateY(-3px)}}
.stat-icon{{font-size:22px;margin-bottom:8px}}
.stat-val{{
font-family:'Poppins',sans-serif;
font-size:15px;font-weight:800;letter-spacing:-.3px;color:#fff;
margin-bottom:3px;
}}
.stat-lbl{{font-size:10px;font-weight:600;letter-spacing:.5px;text-transform:uppercase;color:var(--text3)}}
/* ─── FOOTER ─── */
footer{{
text-align:center;padding:20px 0;
border-top:1px solid var(--border);
}}
.footer-tags{{display:flex;justify-content:center;gap:16px;flex-wrap:wrap;margin-bottom:12px}}
.ftag{{
display:flex;align-items:center;gap:6px;
font-size:12px;font-weight:600;color:var(--text3);
}}
.ftag i{{font-size:10px}}
.fcopy{{font-size:12px;color:var(--text3)}}
/* ─── TOAST ─── */
#toast{{
position:fixed;bottom:24px;left:50%;z-index:999;
transform:translateX(-50%) translateY(120px);
background:var(--card2);
border:1px solid var(--border2);
border-radius:20px;padding:16px 20px;
display:flex;align-items:center;gap:14px;
box-shadow:0 24px 80px rgba(0,0,0,.7),0 0 0 1px rgba(123,92,245,.2);
transition:transform .5s cubic-bezier(.16,1,.3,1);
max-width:360px;width:calc(100% - 32px);
}}
#toast.show{{transform:translateX(-50%) translateY(0)}}
.toast-icon-wrap{{
width:44px;height:44px;border-radius:14px;flex-shrink:0;
display:flex;align-items:center;justify-content:center;font-size:20px;
}}
.t-body{{flex:1}}
.t-title{{font-size:14px;font-weight:800;color:#fff;margin-bottom:3px;font-family:'Poppins',sans-serif}}
.t-sub{{font-size:12px;color:var(--text2);line-height:1.5}}
#t-x{{background:rgba(255,255,255,.08);border:none;border-radius:10px;
width:32px;height:32px;color:var(--text2);cursor:pointer;font-size:13px;
display:flex;align-items:center;justify-content:center;flex-shrink:0;
transition:all .2s}}
#t-x:hover{{background:rgba(255,255,255,.15);color:#fff}}
/* ─── RESPONSIVE ─── */
@media(max-width:600px){{
.stats-row{{grid-template-columns:repeat(2,1fr)}}
.players-grid{{grid-template-columns:repeat(3,1fr);gap:10px}}
.app-icon{{width:52px;height:52px;border-radius:16px;font-size:24px}}
.app-feats{{display:none}}
.vol-r{{width:48px}}
.nav-badge{{display:none}}
}}
</style>
</head>
<body>
<div class="bg-wrap">
<div class="bg-glow g1"></div>
<div class="bg-glow g2"></div>
<div class="bg-glow g3"></div>
<div class="bg-grid"></div>
</div>
<div class="page">
<!-- NAV -->
<nav>
<div class="nav-logo">
<div class="logo-icon">🎬</div>
<div class="logo-name">Love<b>ToRide</b></div>
</div>
<div class="nav-right">
<div class="nav-badge"><i class="fas fa-circle"></i> Secure Stream</div>
<a href="https://t.me/lovetorideworld" target="_blank" class="btn-tg-nav">
<i class="fab fa-telegram-plane"></i> Join Channel
</a>
</div>
</nav>
<!-- COUNTDOWN -->
<div id="cd-section">
<div class="timer-wrap">
<svg class="timer-svg" viewBox="0 0 180 180">
<defs>
<linearGradient id="tg" x1="0%" y1="0%" x2="100%" y2="100%">
<stop offset="0%" stop-color="#7B5CF5"/>
<stop offset="40%" stop-color="#F0507E"/>
<stop offset="70%" stop-color="#4E9BFF"/>
<stop offset="100%" stop-color="#00D4AA"/>
</linearGradient>
</defs>
<circle class="t-track" cx="90" cy="90" r="80"/>
<circle class="t-prog" id="tprog" cx="90" cy="90" r="80"
transform="rotate(-90 90 90)"/>
</svg>
<div class="t-orbit" id="torbit"></div>
<div class="timer-inner">
<div class="timer-num" id="tnum">5</div>
<div class="timer-label">seconds</div>
</div>
</div>
<div class="cd-title">Getting Your <span>Stream Ready</span></div>
<div class="cd-sub">Decrypting and verifying your file securely…</div>
<div class="cd-steps">
<div class="cd-step on" id="s1"><i class="fas fa-shield-halved"></i> Decrypting</div>
<div class="step-arrow"><i class="fas fa-chevron-right"></i></div>
<div class="cd-step" id="s2"><i class="fas fa-check-double"></i> Verifying</div>
<div class="step-arrow"><i class="fas fa-chevron-right"></i></div>
<div class="cd-step" id="s3"><i class="fas fa-play-circle"></i> Streaming</div>
</div>
</div>
<!-- PLAYER SECTION -->
<div id="ps">
<!-- Video player -->
<div class="video-section">
<div class="video-top-bar">
<div class="vtb-left">
<div class="live-dot">● LIVE STREAM</div>
</div>
<div class="vtb-right">
<button class="icon-btn" id="pipbtn" title="Picture in Picture"><i class="fas fa-clone"></i></button>
<button class="icon-btn" id="fsbtn" title="Fullscreen"><i class="fas fa-expand"></i></button>
</div>
</div>
<div class="vid-frame" id="vf">
<video id="vid" preload="auto" playsinline autoplay>
    <source src="/watch/{file_id}/{filename}" type="video/mp4">
</video>
<div class="vbuf" id="vbuf"><div class="buf-spin"></div></div>
<div class="cpop-w"><div class="cpop-ico" id="cpico"><i class="fas fa-play"></i></div></div>
<div class="ctrl" id="ctrl">
<div class="seekbar" id="seekbar">
<div class="sb-buf" id="sbbuf"></div>
<div class="sb-p" id="sbp"></div>
<div class="sb-thumb" id="sbth"></div>
<div class="sb-tip" id="sbtip">0:00</div>
</div>
<div class="ctrl-row">
<button class="cb" id="pbtn"><i class="fas fa-play"></i></button>
<button class="cb" id="bbtn"><i class="fas fa-backward-step"></i><span style="font-size:9px">10</span></button>
<button class="cb" id="fbtn"><i class="fas fa-forward-step"></i><span style="font-size:9px">10</span></button>
<div class="vol-g">
<button class="cb" id="mbtn"><i class="fas fa-volume-high"></i></button>
<input type="range" class="vol-r" id="volr" min="0" max="1" step="0.02" value="1">
</div>
<span class="t-disp" id="tdisp">0:00 / 0:00</span>
<div style="margin-left:auto;display:flex;align-items:center;gap:2px;position:relative">
<button class="cb" id="spdbtn">1×</button>
<div class="spop" id="spop">
<div class="si" data-s="0.25">0.25×</div>
<div class="si" data-s="0.5">0.5×</div>
<div class="si" data-s="0.75">0.75×</div>
<div class="si sel" data-s="1">1×</div>
<div class="si" data-s="1.25">1.25×</div>
<div class="si" data-s="1.5">1.5×</div>
<div class="si" data-s="2">2×</div>
</div>
</div>
</div>
</div>
</div>
</div>
<!-- Info Card -->
<div class="info-card">
<div class="info-left">
<div class="info-fname" id="pfname">{filename}</div>
<div class="info-tags">
<div class="tag tag-purple"><i class="fas fa-bolt"></i> Direct Stream</div>
<div class="tag tag-teal"><i class="fas fa-shield-halved"></i> Encrypted</div>
<div class="tag tag-blue" id="dur-tag"><i class="fas fa-clock"></i> Loading…</div>
</div>
</div>
<a id="dlbtn" href="/watch/{file_id}/{filename}" download class="btn-download">
<i class="fas fa-download"></i> Download File
</a>
</div>
<!-- Stats Row -->
<div class="stats-row">
<div class="stat-box">
<div class="stat-icon">⚡</div>
<div class="stat-val" style="color:var(--yellow)">Fast</div>
<div class="stat-lbl">Transfer</div>
</div>
<div class="stat-box">
<div class="stat-icon">🔒</div>
<div class="stat-val" style="color:var(--teal2)">E2E</div>
<div class="stat-lbl">Encrypted</div>
</div>
<div class="stat-box">
<div class="stat-icon">🎬</div>
<div class="stat-val" style="color:var(--purple2)">HD</div>
<div class="stat-lbl">Quality</div>
</div>
<div class="stat-box">
<div class="stat-icon">∞</div>
<div class="stat-val" style="color:var(--pink2)">None</div>
<div class="stat-lbl">Limits</div>
</div>
</div>
<!-- External Players -->
<div class="section-title">
<h2>Open in External Player</h2>
<span class="badge">HEVC · Multi-Audio</span>
</div>
<div class="players-grid">
<!-- VLC -->
<div class="player-card pc-vlc" onclick="openIn('vlc')">
<div class="app-icon" style="background:linear-gradient(145deg,#FF8C00,#E65000)">
<svg width="34" height="34" viewBox="0 0 100 100">
<polygon points="50,8 93,88 7,88" fill="rgba(255,255,255,.9)"/>
<rect x="32" y="64" width="36" height="20" rx="5" fill="#FF8C00"/>
<rect x="40" y="52" width="20" height="14" rx="3" fill="#FF8C00"/>
<circle cx="50" cy="40" r="13" fill="#FF8C00"/>
<circle cx="50" cy="40" r="5" fill="white"/>
</svg>
</div>
<div class="app-name">VLC Player</div>
<div class="app-feats">
<div class="app-feat"><i class="fas fa-check-circle"></i> HEVC / H.265</div>
<div class="app-feat"><i class="fas fa-check-circle"></i> All Codecs</div>
</div>
<button class="btn-open"><i class="fas fa-external-link-alt"></i> Open Now</button>
</div>
<!-- MX Player -->
<div class="player-card pc-mx" onclick="openIn('mx')">
<div class="app-icon" style="background:linear-gradient(145deg,#1976D2,#0D47A1)">
<svg width="34" height="34" viewBox="0 0 100 100">
<circle cx="50" cy="50" r="36" fill="rgba(255,255,255,.1)"/>
<polygon points="37,28 74,50 37,72" fill="white"/>
</svg>
</div>
<div class="app-name">MX Player</div>
<div class="app-feats">
<div class="app-feat"><i class="fas fa-check-circle"></i> Multi-Audio</div>
<div class="app-feat"><i class="fas fa-check-circle"></i> HW Decode</div>
</div>
<button class="btn-open"><i class="fas fa-external-link-alt"></i> Open Now</button>
</div>
<!-- PlayIt -->
<div class="player-card pc-pi" onclick="openIn('playit')">
<div class="app-icon" style="background:linear-gradient(145deg,#00B894,#007A60)">
<svg width="34" height="34" viewBox="0 0 100 100">
<circle cx="50" cy="50" r="36" fill="rgba(255,255,255,.1)"/>
<circle cx="50" cy="50" r="20" fill="rgba(255,255,255,.12)"/>
<polygon points="41,33 67,50 41,67" fill="white"/>
</svg>
</div>
<div class="app-name">PlayIt</div>
<div class="app-feats">
<div class="app-feat"><i class="fas fa-check-circle"></i> Fast Stream</div>
<div class="app-feat"><i class="fas fa-check-circle"></i> Smooth HW</div>
</div>
<button class="btn-open"><i class="fas fa-external-link-alt"></i> Open Now</button>
</div>
</div>
<!-- Telegram Channel Card -->
<div class="tg-card">
<div class="tg-inner">
<div class="tg-icon-wrap"><i class="fas fa-film"></i></div>
<div class="tg-text">
<div class="tg-label">Official Channel</div>
<div class="tg-name">Hollywood Tamil Dubbed</div>
<div class="tg-desc">🎬 Latest Hollywood blockbusters dubbed in Tamil · HD Quality · Updated daily · 50,000+ members</div>
</div>
<a href="https://t.me/+6eWQ0W8Q5xEyMDM0" target="_blank" class="btn-join">
<i class="fab fa-telegram-plane"></i> Join Free
</a>
</div>
</div>
<!-- Footer -->
<footer>
<div class="footer-tags">
<div class="ftag"><i class="fas fa-shield-halved" style="color:var(--purple2)"></i> End-to-End Encrypted</div>
<div class="ftag"><i class="fas fa-server" style="color:var(--blue2)"></i> No Files Stored</div>
<div class="ftag"><i class="fas fa-bolt" style="color:var(--yellow)"></i> Direct Link Streaming</div>
<div class="ftag"><i class="fas fa-infinity" style="color:var(--teal2)"></i> No Bandwidth Limits</div>
</div>
<div class="fcopy">© 2026 LoveToRide · Premium File Streaming Platform</div>
</footer>
</div>
</div>
<!-- Toast -->
<div id="toast">
<div class="toast-icon-wrap" id="t-ico-wrap" style="background:rgba(255,140,0,.15)">
<span id="t-ico">🎬</span>
</div>
<div class="t-body">
<div class="t-title" id="t-title">Opening player…</div>
<div class="t-sub" id="t-sub">Install the app if it doesn't launch automatically.</div>
</div>
<button id="t-x" onclick="closeToast()"><i class="fas fa-xmark"></i></button>
</div>
<script>
const VIDEO_URL = "/watch/{file_id}/{filename}";
const CIRC = 2 * Math.PI * 80; // 502.65
/* ─── COUNTDOWN ─── */
let rem = 5;
const tprog = document.getElementById('tprog');
const tnum = document.getElementById('tnum');
const torbit= document.getElementById('torbit');
tprog.style.strokeDasharray = CIRC;
tprog.style.strokeDashoffset = CIRC;
const cdi = setInterval(() => {{
rem--;
tprog.style.strokeDashoffset = CIRC * (rem / 5);
tnum.textContent = rem > 0 ? rem : '▶';
if (rem === 3) {{ ss('s1','ok'); ss('s2','on'); }}
if (rem === 1) {{ ss('s2','ok'); ss('s3','on'); }}
if (rem <= 0) {{
clearInterval(cdi);
ss('s3','ok');
torbit.style.animation = 'none';
setTimeout(() => {{
document.getElementById('cd-section').style.display = 'none';
document.getElementById('ps').classList.add('show');
initPlayer();
}}, 200);
}}
}}, 1000);
function ss(id, cls) {{
const el = document.getElementById(id);
el.className = 'cd-step ' + cls;
}}
/* ─── PLAYER ─── */
const vid = document.getElementById('vid');
const vf = document.getElementById('vf');
const pbtn = document.getElementById('pbtn');
const bbtn = document.getElementById('bbtn');
const fbtn = document.getElementById('fbtn');
const mbtn = document.getElementById('mbtn');
const volr = document.getElementById('volr');
const tdisp = document.getElementById('tdisp');
const seekbar= document.getElementById('seekbar');
const sbbuf = document.getElementById('sbbuf');
const sbp = document.getElementById('sbp');
const sbth = document.getElementById('sbth');
const sbtip = document.getElementById('sbtip');
const spdbtn = document.getElementById('spdbtn');
const spop = document.getElementById('spop');
const pipbtn = document.getElementById('pipbtn');
const fsbtn = document.getElementById('fsbtn');
const vbuf = document.getElementById('vbuf');
const cpico = document.getElementById('cpico');
function fmt(s) {{
if (!s || isNaN(s)) return '0:00';
return `${{Math.floor(s/60)}}:${{String(Math.floor(s%60)).padStart(2,'0')}}`;
}}
function syncBtn() {{
pbtn.innerHTML = vid.paused ? '<i class="fas fa-play"></i>' : '<i class="fas fa-pause"></i>';
}}
function pop(t) {{
cpico.innerHTML = `<i class="fas fa-${{t==='play'?'play':'pause'}}"></i>`;
cpico.classList.remove('go'); void cpico.offsetWidth; cpico.classList.add('go');
}}
function toggle() {{
if (vid.paused) {{ vid.play(); pop('play'); }} else {{ vid.pause(); pop('pause'); }}
}}
function initPlayer() {{
vid.load();
setTimeout(() => vid.play().catch(() => {{}}), 200);
}}
// One-tap anywhere to force play if blocked by Chrome autoplay policy
let hasInteracted = false;
document.addEventListener('click', () => {{
    if (!hasInteracted) {{
        hasInteracted = true;
        if (vid.paused) vid.play().catch(() => {{}});
    }}
}}, {{once: true}});
document.addEventListener('touchstart', () => {{
    if (!hasInteracted) {{
        hasInteracted = true;
        if (vid.paused) vid.play().catch(() => {{}});
    }}
}}, {{once: true, passive: true}});

vid.addEventListener('play', syncBtn);
vid.addEventListener('pause', syncBtn);
vid.addEventListener('click', toggle);
pbtn.addEventListener('click', e => {{ e.stopPropagation(); toggle(); }});
bbtn.addEventListener('click', e => {{ e.stopPropagation(); vid.currentTime -= 10; }});
fbtn.addEventListener('click', e => {{ e.stopPropagation(); vid.currentTime += 10; }});
vid.addEventListener('timeupdate', () => {{
const p = vid.duration ? vid.currentTime / vid.duration * 100 : 0;
sbp.style.width = p + '%'; sbth.style.left = p + '%';
tdisp.textContent = fmt(vid.currentTime) + ' / ' + fmt(vid.duration);
}});
vid.addEventListener('progress', () => {{
if (vid.buffered.length && vid.duration)
sbbuf.style.width = (vid.buffered.end(vid.buffered.length-1) / vid.duration * 100) + '%';
}});
vid.addEventListener('loadedmetadata', () => {{
document.getElementById('dur-tag').innerHTML = `<i class="fas fa-clock"></i> ${{fmt(vid.duration)}}`;
}});
vid.addEventListener('waiting', () => vbuf.classList.add('on'));
vid.addEventListener('playing', () => vbuf.classList.remove('on'));
vid.addEventListener('canplay', () => vbuf.classList.remove('on'));
/* Seek */
let drag = false;
function seekTo(e) {{
const r = seekbar.getBoundingClientRect();
const x = Math.max(0, Math.min((e.touches?.[0]?.clientX ?? e.clientX) - r.left, r.width));
if (vid.duration) vid.currentTime = x / r.width * vid.duration;
}}
seekbar.addEventListener('mousedown', e => {{ drag=true; seekTo(e); }});
document.addEventListener('mousemove', e => {{ if(drag) seekTo(e); }});
document.addEventListener('mouseup', () => drag=false);
seekbar.addEventListener('touchstart', e => {{ drag=true; seekTo(e); }}, {{passive:true}});
document.addEventListener('touchmove', e => {{ if(drag) seekTo(e); }}, {{passive:true}});
document.addEventListener('touchend', () => drag=false);
seekbar.addEventListener('mousemove', e => {{
const r = seekbar.getBoundingClientRect();
const x = Math.max(0, Math.min(e.clientX - r.left, r.width));
sbtip.textContent = fmt(x / r.width * (vid.duration||0));
sbtip.style.left = (x / r.width * 100) + '%';
}});
/* Volume */
mbtn.addEventListener('click', e => {{
e.stopPropagation(); vid.muted = !vid.muted;
mbtn.innerHTML = vid.muted ? '<i class="fas fa-volume-xmark"></i>' : '<i class="fas fa-volume-high"></i>';
}});
volr.addEventListener('input', e => {{
e.stopPropagation(); vid.volume = volr.value; vid.muted = vid.volume === 0;
mbtn.innerHTML = (vid.volume===0||vid.muted) ? '<i class="fas fa-volume-xmark"></i>' : '<i class="fas fa-volume-high"></i>';
}});
/* Speed */
spdbtn.addEventListener('click', e => {{ e.stopPropagation(); spop.classList.toggle('on'); }});
spop.querySelectorAll('.si').forEach(el => {{
el.addEventListener('click', e => {{
e.stopPropagation();
vid.playbackRate = parseFloat(el.dataset.s);
spdbtn.textContent = el.dataset.s + '×';
spop.querySelectorAll('.si').forEach(i => i.classList.remove('sel'));
el.classList.add('sel'); spop.classList.remove('on');
}});
}});
document.addEventListener('click', () => spop.classList.remove('on'));
/* PiP */
pipbtn.addEventListener('click', async e => {{
e.stopPropagation();
try {{ document.pictureInPictureElement ? await document.exitPictureInPicture() : await vid.requestPictureInPicture(); }}
catch(_) {{}}
}});
/* Fullscreen */
fsbtn.addEventListener('click', e => {{
e.stopPropagation();
if (!document.fullscreenElement) {{
(vf.requestFullscreen || vf.webkitRequestFullscreen).call(vf);
fsbtn.innerHTML = '<i class="fas fa-compress"></i>';
}} else {{
(document.exitFullscreen || document.webkitExitFullscreen).call(document);
}}
}});
document.addEventListener('fullscreenchange', () => {{
if (!document.fullscreenElement) fsbtn.innerHTML = '<i class="fas fa-expand"></i>';
}});
/* Keyboard */
document.addEventListener('keydown', e => {{
if (['INPUT','TEXTAREA'].includes(document.activeElement.tagName)) return;
switch(e.code) {{
case 'Space': e.preventDefault(); toggle(); break;
case 'ArrowLeft': vid.currentTime -= 5; break;
case 'ArrowRight': vid.currentTime += 5; break;
case 'ArrowUp': vid.volume = Math.min(1,vid.volume+.1); volr.value=vid.volume; break;
case 'ArrowDown': vid.volume = Math.max(0,vid.volume-.1); volr.value=vid.volume; break;
case 'KeyM': mbtn.click(); break;
case 'KeyF': fsbtn.click(); break;
}}
}});
/* Auto-hide controls */
let ht;
function rh() {{
vf.classList.remove('hc'); clearTimeout(ht);
if (!vid.paused) ht = setTimeout(() => vf.classList.add('hc'), 3000);
}}
vf.addEventListener('mousemove', rh);
vf.addEventListener('touchstart', rh, {{passive:true}});
vid.addEventListener('play', () => {{ ht = setTimeout(() => vf.classList.add('hc'), 3000); }});
vid.addEventListener('pause', () => {{ vf.classList.remove('hc'); clearTimeout(ht); }});
/* ─── EXTERNAL PLAYERS ─── */
const APPS = {{
vlc: {{ ico:'🎬', bg:'rgba(255,140,0,.15)', t:'Opening VLC Player…', s:'VLC supports HEVC/H.265 & all audio codecs. Get it at videolan.org', u: x=>`vlc://${{x}}` }},
mx: {{ ico:'▶️', bg:'rgba(25,118,210,.15)', t:'Opening MX Player…', s:'MX Player supports multi-audio tracks & hardware decoding.', u: x=>`intent:${{x}}#Intent;package=com.mxtech.videoplayer.ad;end` }},
playit: {{ ico:'▶', bg:'rgba(0,184,148,.15)', t:'Opening PlayIt Player…', s:'PlayIt provides fast hardware-accelerated smooth playback.', u: x=>`intent:${{x}}#Intent;package=com.playit.videoplayer;end` }}
}};
function openIn(app) {{
const c = APPS[app];
window.location.href = c.u(encodeURIComponent(window.location.origin + VIDEO_URL));
document.getElementById('t-ico').textContent = c.ico;
document.getElementById('t-ico-wrap').style.background = c.bg;
document.getElementById('t-title').textContent = c.t;
document.getElementById('t-sub').textContent = c.s;
const t = document.getElementById('toast');
t.classList.add('show');
clearTimeout(window._tt);
window._tt = setTimeout(() => t.classList.remove('show'), 7000);
}}
function closeToast() {{ document.getElementById('toast').classList.remove('show'); }}
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
            
            # If file_size is missing (older movies), try to fetch it from the original message!
            if not file_size and movie.get('source_chat_id') and movie.get('source_message_id'):
                try:
                    msg = await self.client.get_messages(movie['source_chat_id'], movie['source_message_id'])
                    if msg:
                        if msg.video:
                            file_size = msg.video.file_size
                        elif msg.document:
                            file_size = msg.document.file_size
                        
                        # Save it back to db so we don't have to fetch it next time
                        if file_size:
                            await movies_col.update_one({'_id': movie['_id']}, {'$set': {'file_size': file_size}})
                except Exception:
                    pass
            
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
            
            # Determine correct mime type so browsers properly demux MKV audio (AAC)
            fake_mp4 = request.query.get('fake_mp4')
            if fake_mp4 == 'true' or filename.lower().endswith('.mkv'):
                # Force mp4 for mkv files to allow Chrome to sniff and demux AAC audio properly
                mime_type = 'video/mp4'
            else:
                mime_type, _ = mimetypes.guess_type(filename)
                mime_type = mime_type or 'video/mp4'
                
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
            bytes_left = length if length > 0 else float('inf')
            
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


    

    async def embed_player(self, request):
        file_id = request.match_info['file_id']
        filename = request.match_info['filename']
        
        # We will load the sleek HTML player here
        html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>LoveToRide · {filename}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Nunito:wght@400;500;600;700;800;900&family=Poppins:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css">
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
html{{scroll-behavior:smooth}}
:root{{
--bg:#0B0F1E;
--card:#131929;
--card2:#1A2238;
--card3:#1F2940;
--purple:#7B5CF5;
--purple2:#9B7DFF;
--pink:#F0507E;
--pink2:#FF6B9D;
--blue:#4E9BFF;
--blue2:#72B4FF;
--teal:#00D4AA;
--teal2:#00F5C4;
--orange:#FF8C42;
--yellow:#FFD166;
--white:#FFFFFF;
--text:#E8EEFF;
--text2:#9BA3BC;
--text3:#6B7490;
--border:rgba(255,255,255,0.07);
--border2:rgba(255,255,255,0.12);
--glow-purple:rgba(123,92,245,0.4);
--glow-pink:rgba(240,80,126,0.4);
--glow-teal:rgba(0,212,170,0.3);
}}
body{{
font-family:'Nunito',sans-serif;
background:var(--bg);
color:var(--text);
min-height:100vh;
overflow-x:hidden;
}}
/* ─── ANIMATED BG ─── */
.bg-wrap{{position:fixed;inset:0;z-index:0;overflow:hidden;pointer-events:none}}
.bg-glow{{
position:absolute;border-radius:50%;filter:blur(120px);opacity:.25;
animation:bgFloat 15s ease-in-out infinite alternate;
}}
.bg-glow.g1{{width:700px;height:700px;background:var(--purple);top:-200px;left:-200px;animation-duration:18s}}
.bg-glow.g2{{width:600px;height:600px;background:var(--pink);bottom:-150px;right:-100px;animation-duration:22s;animation-direction:alternate-reverse}}
.bg-glow.g3{{width:400px;height:400px;background:var(--blue);top:40%;left:50%;animation-duration:14s}}
@keyframes bgFloat{{
0%{{transform:translate(0,0) scale(1)}}
100%{{transform:translate(50px,-50px) scale(1.15)}}
}}
/* Subtle grid */
.bg-grid{{
position:absolute;inset:0;
background-image:linear-gradient(rgba(255,255,255,.025) 1px,transparent 1px),
linear-gradient(90deg,rgba(255,255,255,.025) 1px,transparent 1px);
background-size:40px 40px;
}}
/* ─── LAYOUT ─── */
.page{{position:relative;z-index:1;width:100%;height:100vh;margin:0;padding:0;display:flex;align-items:center;justify-content:center;}}
/* ─── NAVBAR ─── */
nav{{
display:flex;align-items:center;justify-content:space-between;
padding:18px 0 16px;
border-bottom:1px solid var(--border);
margin-bottom:32px;
}}
.nav-logo{{
display:flex;align-items:center;gap:10px;
}}
.logo-icon{{
width:38px;height:38px;border-radius:12px;
background:linear-gradient(135deg,var(--purple),var(--pink));
display:flex;align-items:center;justify-content:center;
font-size:18px;
box-shadow:0 4px 20px var(--glow-purple);
}}
.logo-name{{
font-family:'Poppins',sans-serif;
font-size:20px;font-weight:800;letter-spacing:-.5px;
}}
.logo-name b{{
background:linear-gradient(90deg,var(--purple2),var(--pink2));
-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;
}}
.nav-right{{display:flex;align-items:center;gap:10px}}
.nav-badge{{
display:flex;align-items:center;gap:6px;
font-size:12px;font-weight:700;
padding:7px 14px;border-radius:20px;
background:rgba(0,212,170,.1);
border:1px solid rgba(0,212,170,.25);
color:var(--teal2);
}}
.nav-badge i{{font-size:10px;animation:pulse 2s infinite}}
@keyframes pulse{{0%,100%{{opacity:1}}50%{{opacity:.4}}}}
.btn-tg-nav{{
display:flex;align-items:center;gap:7px;
font-size:13px;font-weight:700;
padding:9px 18px;border-radius:20px;
background:linear-gradient(135deg,var(--purple),var(--pink));
color:#fff;text-decoration:none;
box-shadow:0 4px 20px var(--glow-purple);
transition:all .25s;border:none;cursor:pointer;
}}
.btn-tg-nav:hover{{transform:translateY(-2px);box-shadow:0 8px 30px var(--glow-purple)}}
/* ─── COUNTDOWN ─── */
#cd-section{{
display:flex;flex-direction:column;align-items:center;
padding:40px 0 60px;
animation:fadeUp .6s ease both;
}}
@keyframes fadeUp{{from{{opacity:0;transform:translateY(24px)}}to{{opacity:1;transform:translateY(0)}}}}
/* Circular progress timer */
.timer-wrap{{
position:relative;width:180px;height:180px;
margin-bottom:36px;
}}
.timer-svg{{width:100%;height:100%;transform:rotate(-90deg)}}
.t-track{{fill:none;stroke:rgba(255,255,255,.06);stroke-width:6}}
.t-prog{{
fill:none;stroke-width:6;stroke-linecap:round;
stroke:url(#tg);
stroke-dasharray:502;stroke-dashoffset:502;
transition:stroke-dashoffset .12s linear;
filter:drop-shadow(0 0 8px rgba(123,92,245,.8));
}}
.timer-inner{{
position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;
gap:2px;
}}
.timer-num{{
font-family:'Poppins',sans-serif;
font-size:56px;font-weight:900;line-height:1;letter-spacing:-3px;
background:linear-gradient(160deg,var(--white),var(--purple2),var(--pink2));
-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;
}}
.timer-label{{font-size:10px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:var(--text3)}}
/* Orbit dot */
.t-orbit{{position:absolute;inset:-4px;border-radius:50%;animation:orb 1.1s linear infinite}}
.t-orbit::before{{
content:'';position:absolute;top:8px;left:50%;transform:translateX(-50%);
width:10px;height:10px;border-radius:50%;
background:var(--pink2);
box-shadow:0 0 14px var(--pink),0 0 28px var(--glow-pink);
}}
@keyframes orb{{to{{transform:rotate(360deg)}}}}
.cd-title{{
font-family:'Poppins',sans-serif;
font-size:26px;font-weight:800;letter-spacing:-.5px;
text-align:center;margin-bottom:8px;
}}
.cd-title span{{
background:linear-gradient(90deg,var(--purple2),var(--pink2),var(--blue2));
-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;
}}
.cd-sub{{font-size:14px;color:var(--text2);text-align:center;margin-bottom:32px;font-weight:500}}
/* Steps — pill row */
.cd-steps{{
display:flex;align-items:center;gap:8px;
background:var(--card);
border:1px solid var(--border);
border-radius:20px;padding:6px;
}}
.cd-step{{
display:flex;align-items:center;gap:8px;
padding:10px 20px;border-radius:16px;
font-size:12px;font-weight:700;letter-spacing:.3px;
color:var(--text3);transition:all .4s cubic-bezier(.16,1,.3,1);
}}
.cd-step i{{font-size:11px}}
.cd-step.on{{
background:linear-gradient(135deg,var(--purple),var(--pink));
color:#fff;
box-shadow:0 4px 20px var(--glow-purple);
}}
.cd-step.ok{{color:var(--teal2);background:rgba(0,212,170,.1)}}
.step-arrow{{color:var(--text3);font-size:10px}}
/* ─── PLAYER SECTION ─── */
#ps{{display:none}}
#ps.show{{display:block;animation:fadeUp .6s ease both}}
/* ─── VIDEO PLAYER ─── */
.video-section{{
border-radius: 0;
border: none;
width: 100%;
max-height: 100vh;

background:var(--card);
border-radius:24px;
overflow:hidden;
border:1px solid var(--border);
box-shadow:0 24px 80px rgba(0,0,0,.6),0 0 0 1px rgba(255,255,255,.04);
margin-bottom:0;
}}
.video-top-bar{{
display:flex;align-items:center;justify-content:space-between;
padding:14px 18px;
border-bottom:1px solid var(--border);
}}
.vtb-left{{display:flex;align-items:center;gap:10px}}
.live-dot{{
display:flex;align-items:center;gap:6px;
background:rgba(0,212,170,.12);
border:1px solid rgba(0,212,170,.3);
padding:5px 12px;border-radius:20px;
font-size:11px;font-weight:700;color:var(--teal2);letter-spacing:.5px;
}}
.live-dot::before{{
content:'';width:6px;height:6px;border-radius:50%;
background:var(--teal2);animation:pulse 1.5s infinite;
box-shadow:0 0 8px var(--teal);
}}
.vtb-right{{display:flex;align-items:center;gap:8px}}
.icon-btn{{
width:34px;height:34px;border-radius:10px;border:none;cursor:pointer;
background:rgba(255,255,255,.06);color:var(--text2);
display:flex;align-items:center;justify-content:center;font-size:13px;
transition:all .2s;
}}
.icon-btn:hover{{background:rgba(255,255,255,.12);color:#fff}}
/* Video frame */
.vid-frame{{
position:relative;background:#000;
}}
.vid-frame::before{{
content:'';position:absolute;top:0;left:0;right:0;height:2px;z-index:10;
background:linear-gradient(90deg,var(--purple),var(--pink),var(--blue),var(--teal));
background-size:300% 100%;animation:rainbowSlide 3s linear infinite;
}}
@keyframes rainbowSlide{{0%{{background-position:0% 0}}100%{{background-position:300% 0}}}}
#vid{{display:block;width:100%;aspect-ratio:16/9;background:#000;cursor:pointer}}
/* Buffer overlay */
.vbuf{{
position:absolute;inset:0;display:none;
align-items:center;justify-content:center;
background:rgba(11,15,30,.7);backdrop-filter:blur(4px);
}}
.vbuf.on{{display:flex}}
.buf-spin{{
width:50px;height:50px;border-radius:50%;
border:3px solid rgba(123,92,245,.2);
border-top-color:var(--purple2);
border-right-color:var(--pink2);
animation:spin .7s linear infinite;
}}
@keyframes spin{{to{{transform:rotate(360deg)}}}}
/* Center pop */
.cpop-w{{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;pointer-events:none}}
.cpop-ico{{
width:72px;height:72px;border-radius:50%;
background:linear-gradient(135deg,rgba(123,92,245,.4),rgba(240,80,126,.4));
backdrop-filter:blur(8px);border:1.5px solid rgba(255,255,255,.25);
display:flex;align-items:center;justify-content:center;
font-size:24px;color:#fff;opacity:0;
}}
.cpop-ico.go{{animation:cpAnim .55s forwards}}
@keyframes cpAnim{{
0%{{opacity:1;transform:scale(.8)}}
55%{{opacity:1;transform:scale(1.1)}}
100%{{opacity:0;transform:scale(1.4)}}
}}
/* ─── CONTROL BAR ─── */
.ctrl{{
position:absolute;bottom:0;left:0;right:0;
background:linear-gradient(transparent,rgba(11,15,30,.98));
padding:52px 18px 14px;
transition:opacity .3s;
}}
.vid-frame.hc .ctrl{{opacity:0;pointer-events:none}}
.vid-frame.hc{{cursor:none}}
/* Seekbar */
.seekbar{{
position:relative;height:4px;background:rgba(255,255,255,.1);
border-radius:10px;cursor:pointer;margin-bottom:14px;transition:height .15s;
}}
.seekbar:hover{{height:6px}}
.sb-buf,.sb-p{{position:absolute;inset:0;height:100%;border-radius:10px}}
.sb-buf{{background:rgba(255,255,255,.15)}}
.sb-p{{
background:linear-gradient(90deg,var(--purple),var(--pink),var(--blue));
width:0%;transition:width .1s linear;
box-shadow:0 0 10px rgba(123,92,245,.6);
}}
.sb-thumb{{
position:absolute;top:50%;width:14px;height:14px;border-radius:50%;
background:#fff;box-shadow:0 0 10px var(--purple2),0 0 20px var(--glow-purple);
transform:translate(-50%,-50%) scale(0);transition:transform .15s;pointer-events:none;
}}
.seekbar:hover .sb-thumb{{transform:translate(-50%,-50%) scale(1)}}
.sb-tip{{
position:absolute;bottom:18px;transform:translateX(-50%);
background:var(--card2);border:1px solid var(--border2);
color:var(--text);font-size:11px;font-weight:700;
padding:4px 10px;border-radius:8px;pointer-events:none;
white-space:nowrap;opacity:0;transition:opacity .15s;
box-shadow:0 4px 16px rgba(0,0,0,.5);
}}
.seekbar:hover .sb-tip{{opacity:1}}
/* Control buttons */
.ctrl-row{{display:flex;align-items:center;gap:2px}}
.cb{{
background:none;border:none;color:rgba(255,255,255,.55);
cursor:pointer;padding:7px 9px;border-radius:10px;font-size:14px;
transition:all .2s;display:flex;align-items:center;gap:4px;
}}
.cb:hover{{background:rgba(255,255,255,.1);color:#fff}}
#pbtn{{font-size:19px}}
.t-disp{{
font-size:12px;font-weight:700;color:rgba(255,255,255,.5);
padding:0 8px;white-space:nowrap;letter-spacing:.3px;
}}
.vol-g{{display:flex;align-items:center;gap:6px}}
.vol-r{{
-webkit-appearance:none;appearance:none;
width:72px;height:4px;border-radius:4px;
background:rgba(255,255,255,.18);outline:none;cursor:pointer;
}}
.vol-r::-webkit-slider-thumb{{
-webkit-appearance:none;width:13px;height:13px;
border-radius:50%;background:#fff;cursor:pointer;
box-shadow:0 0 8px var(--purple2);
}}
.spop{{
position:absolute;bottom:58px;right:0;
background:var(--card2);border:1px solid var(--border2);
border-radius:14px;display:none;z-index:30;min-width:120px;
box-shadow:0 20px 60px rgba(0,0,0,.8);overflow:hidden;
}}
.spop.on{{display:block}}
.si{{
padding:10px 18px;font-size:13px;font-weight:600;
cursor:pointer;color:var(--text2);transition:all .15s;
}}
.si:hover,.si.sel{{background:rgba(123,92,245,.15);color:var(--purple2)}}
/* ─── INFO CARD BELOW PLAYER ─── */
.info-card{{display:none;
display:flex;flex-wrap:wrap;gap:16px;align-items:center;
background:var(--card);border:1px solid var(--border);
border-radius:20px;padding:18px 22px;
margin-bottom:0;
box-shadow:0 8px 40px rgba(0,0,0,.3);
}}
.info-left{{flex:1;min-width:0}}
.info-fname{{
font-family:'Poppins',sans-serif;
font-size:16px;font-weight:700;letter-spacing:-.3px;
color:#fff;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
margin-bottom:8px;
}}
.info-tags{{display:flex;flex-wrap:wrap;gap:8px}}
.tag{{
display:flex;align-items:center;gap:5px;
font-size:11px;font-weight:700;letter-spacing:.3px;
padding:5px 12px;border-radius:20px;
}}
.tag-purple{{background:rgba(123,92,245,.15);color:var(--purple2);border:1px solid rgba(123,92,245,.25)}}
.tag-teal{{background:rgba(0,212,170,.12);color:var(--teal2);border:1px solid rgba(0,212,170,.25)}}
.tag-blue{{background:rgba(78,155,255,.12);color:var(--blue2);border:1px solid rgba(78,155,255,.25)}}
/* Download button */
.btn-download{{
display:flex;align-items:center;gap:10px;
padding:13px 26px;border-radius:16px;
font-family:'Poppins',sans-serif;
font-size:14px;font-weight:700;
color:#fff;text-decoration:none;border:none;cursor:pointer;
background:linear-gradient(135deg,var(--purple),var(--pink));
box-shadow:0 6px 28px var(--glow-purple);
transition:all .25s;position:relative;overflow:hidden;
white-space:nowrap;
}}
.btn-download::before{{
content:'';position:absolute;inset:0;
background:linear-gradient(105deg,transparent 35%,rgba(255,255,255,.2) 50%,transparent 65%);
background-size:200% 100%;animation:shimmer 2.5s ease-in-out infinite;
}}
.btn-download:hover{{transform:translateY(-3px);box-shadow:0 12px 40px var(--glow-purple)}}
@keyframes shimmer{{0%{{background-position:-200% 0}}100%{{background-position:200% 0}}}}
/* ─── EXTERNAL PLAYERS ─── */
.section-title{{display:none;
display:flex;align-items:center;gap:12px;
margin-bottom:16px;
}}
.section-title h2{{
font-family:'Poppins',sans-serif;
font-size:18px;font-weight:800;letter-spacing:-.3px;
color:#fff;
}}
.section-title .badge{{
font-size:10px;font-weight:700;letter-spacing:1px;text-transform:uppercase;
padding:4px 12px;border-radius:20px;
background:rgba(255,140,66,.15);color:var(--orange);
border:1px solid rgba(255,140,66,.3);
}}
.players-grid{{display:none;
display:grid;grid-template-columns:repeat(3,1fr);gap:14px;
margin-bottom:24px;
}}
.player-card{{
background:var(--card);border:1px solid var(--border);
border-radius:22px;padding:24px 16px 20px;
display:flex;flex-direction:column;align-items:center;gap:12px;
cursor:pointer;text-decoration:none;color:var(--text);
transition:all .3s cubic-bezier(.16,1,.3,1);
position:relative;overflow:hidden;
}}
/* Hover top shimmer */
.player-card::before{{
content:'';position:absolute;top:0;left:0;right:0;height:2px;
transform:scaleX(0);transition:transform .3s ease;
transform-origin:left;
}}
.pc-vlc::before{{background:linear-gradient(90deg,#FF8C00,#FFD166)}}
.pc-mx::before{{background:linear-gradient(90deg,#4E9BFF,#00D4AA)}}
.pc-pi::before{{background:linear-gradient(90deg,#00D4AA,#7B5CF5)}}
.player-card:hover{{
transform:translateY(-6px);
border-color:var(--border2);
box-shadow:0 20px 60px rgba(0,0,0,.5);
}}
.player-card:hover::before{{transform:scaleX(1)}}
/* App icon */
.app-icon{{
width:64px;height:64px;border-radius:20px;
display:flex;align-items:center;justify-content:center;
font-size:30px;
box-shadow:0 8px 24px rgba(0,0,0,.4);
position:relative;overflow:hidden;
}}
.app-icon::after{{
content:'';position:absolute;inset:0;
background:linear-gradient(145deg,rgba(255,255,255,.15),transparent 60%);
}}
.app-name{{
font-family:'Poppins',sans-serif;
font-size:15px;font-weight:800;letter-spacing:-.2px;color:#fff;
text-align:center;
}}
.app-feats{{
display:flex;flex-direction:column;align-items:center;gap:4px;width:100%;
}}
.app-feat{{
display:flex;align-items:center;gap:6px;
font-size:11px;font-weight:600;color:var(--text2);
}}
.app-feat i{{font-size:9px}}
.pc-vlc .app-feat i{{color:var(--orange)}}
.pc-mx .app-feat i{{color:var(--blue2)}}
.pc-pi .app-feat i{{color:var(--teal2)}}
/* Open buttons */
.btn-open{{
display:flex;align-items:center;justify-content:center;gap:8px;
width:100%;padding:11px;border-radius:14px;
font-size:13px;font-weight:800;letter-spacing:.3px;
border:none;cursor:pointer;color:#fff;
transition:all .25s;position:relative;overflow:hidden;
}}
.btn-open::before{{
content:'';position:absolute;inset:0;
background:linear-gradient(105deg,transparent 35%,rgba(255,255,255,.15) 50%,transparent 65%);
background-size:200% 100%;
}}
.btn-open:hover::before{{animation:shimmer 1.5s ease-in-out infinite}}
.pc-vlc .btn-open{{background:linear-gradient(135deg,#FF8C00,#FF6600);box-shadow:0 4px 20px rgba(255,140,0,.3)}}
.pc-mx .btn-open{{background:linear-gradient(135deg,#1976D2,#0288D1);box-shadow:0 4px 20px rgba(30,118,210,.3)}}
.pc-pi .btn-open{{background:linear-gradient(135deg,#00B894,#00D4AA);box-shadow:0 4px 20px rgba(0,212,170,.3)}}
.btn-open:hover{{transform:scale(1.02)}}
/* ─── TELEGRAM CARD ─── */
.tg-card{{
border-radius:24px;overflow:hidden;
margin-bottom:24px;
position:relative;
background:linear-gradient(135deg,rgba(123,92,245,.2),rgba(240,80,126,.15),rgba(78,155,255,.1));
border:1px solid rgba(123,92,245,.25);
box-shadow:0 16px 60px rgba(123,92,245,.15);
}}
/* Animated background pattern */
.tg-card::before{{
content:'';position:absolute;inset:0;
background:
radial-gradient(circle at 20% 50%,rgba(123,92,245,.15),transparent 50%),
radial-gradient(circle at 80% 50%,rgba(240,80,126,.12),transparent 50%);
animation:tgBg 6s ease-in-out infinite alternate;
}}
@keyframes tgBg{{
0%{{transform:scale(1)}}100%{{transform:scale(1.1)}}
}}
.tg-inner{{
position:relative;z-index:1;
padding:28px 28px;
display:flex;flex-wrap:wrap;align-items:center;gap:20px;
}}
.tg-icon-wrap{{
width:64px;height:64px;border-radius:20px;flex-shrink:0;
background:linear-gradient(135deg,var(--purple),var(--pink));
display:flex;align-items:center;justify-content:center;
font-size:28px;color:#fff;
box-shadow:0 8px 30px var(--glow-purple);
position:relative;
}}
.tg-icon-wrap::after{{
content:'';position:absolute;inset:0;border-radius:20px;
background:linear-gradient(145deg,rgba(255,255,255,.2),transparent);
}}
.tg-text{{flex:1;min-width:160px}}
.tg-label{{
font-size:11px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;
color:var(--purple2);margin-bottom:6px;
display:flex;align-items:center;gap:6px;
}}
.tg-label::before{{content:'';width:16px;height:2px;background:var(--purple2);border-radius:2px}}
.tg-name{{
font-family:'Poppins',sans-serif;
font-size:20px;font-weight:800;letter-spacing:-.5px;color:#fff;
margin-bottom:6px;
}}
.tg-desc{{font-size:13px;color:rgba(255,255,255,.6);font-weight:500;line-height:1.5}}
.btn-join{{
display:flex;align-items:center;gap:10px;
padding:14px 28px;border-radius:16px;
font-family:'Poppins',sans-serif;
font-size:14px;font-weight:800;
color:#fff;text-decoration:none;border:none;cursor:pointer;
background:linear-gradient(135deg,#229ED9,#1A7FB5);
box-shadow:0 6px 28px rgba(34,158,217,.35);
transition:all .25s;white-space:nowrap;
position:relative;overflow:hidden;
}}
.btn-join::before{{
content:'';position:absolute;inset:0;
background:linear-gradient(105deg,transparent 35%,rgba(255,255,255,.2) 50%,transparent 65%);
background-size:200% 100%;animation:shimmer 2s ease-in-out 1s infinite;
}}
.btn-join:hover{{transform:translateY(-3px);box-shadow:0 12px 40px rgba(34,158,217,.5)}}
.btn-join i{{font-size:16px}}
/* ─── STATS ROW ─── */
.stats-row{{display:none;
display:grid;grid-template-columns:repeat(4,1fr);gap:12px;
margin-bottom:24px;
}}
.stat-box{{
background:var(--card);border:1px solid var(--border);
border-radius:18px;padding:18px 14px;
text-align:center;
transition:all .25s;
}}
.stat-box:hover{{border-color:var(--border2);transform:translateY(-3px)}}
.stat-icon{{font-size:22px;margin-bottom:8px}}
.stat-val{{
font-family:'Poppins',sans-serif;
font-size:15px;font-weight:800;letter-spacing:-.3px;color:#fff;
margin-bottom:3px;
}}
.stat-lbl{{font-size:10px;font-weight:600;letter-spacing:.5px;text-transform:uppercase;color:var(--text3)}}
/* ─── FOOTER ─── */
footer{{
text-align:center;padding:20px 0;
border-top:1px solid var(--border);
}}
.footer-tags{{display:flex;justify-content:center;gap:16px;flex-wrap:wrap;margin-bottom:12px}}
.ftag{{
display:flex;align-items:center;gap:6px;
font-size:12px;font-weight:600;color:var(--text3);
}}
.ftag i{{font-size:10px}}
.fcopy{{font-size:12px;color:var(--text3)}}
/* ─── TOAST ─── */
#toast{{
position:fixed;bottom:24px;left:50%;z-index:999;
transform:translateX(-50%) translateY(120px);
background:var(--card2);
border:1px solid var(--border2);
border-radius:20px;padding:16px 20px;
display:flex;align-items:center;gap:14px;
box-shadow:0 24px 80px rgba(0,0,0,.7),0 0 0 1px rgba(123,92,245,.2);
transition:transform .5s cubic-bezier(.16,1,.3,1);
max-width:360px;width:calc(100% - 32px);
}}
#toast.show{{transform:translateX(-50%) translateY(0)}}
.toast-icon-wrap{{
width:44px;height:44px;border-radius:14px;flex-shrink:0;
display:flex;align-items:center;justify-content:center;font-size:20px;
}}
.t-body{{flex:1}}
.t-title{{font-size:14px;font-weight:800;color:#fff;margin-bottom:3px;font-family:'Poppins',sans-serif}}
.t-sub{{font-size:12px;color:var(--text2);line-height:1.5}}
#t-x{{background:rgba(255,255,255,.08);border:none;border-radius:10px;
width:32px;height:32px;color:var(--text2);cursor:pointer;font-size:13px;
display:flex;align-items:center;justify-content:center;flex-shrink:0;
transition:all .2s}}
#t-x:hover{{background:rgba(255,255,255,.15);color:#fff}}
/* ─── RESPONSIVE ─── */
@media(max-width:600px){{
.stats-row{{display:none;grid-template-columns:repeat(2,1fr)}}
.players-grid{{display:none;grid-template-columns:repeat(3,1fr);gap:10px}}
.app-icon{{width:52px;height:52px;border-radius:16px;font-size:24px}}
.app-feats{{display:none}}
.vol-r{{width:48px}}
.nav-badge{{display:none}}
}}
</style>
</head>
<body>
<div class="bg-wrap">
<div class="bg-glow g1"></div>
<div class="bg-glow g2"></div>
<div class="bg-glow g3"></div>
<div class="bg-grid"></div>
</div>
<div class="page">
<!-- NAV -->

<!-- COUNTDOWN -->
<!-- PLAYER SECTION -->
<div id="ps" class="show">
<!-- Video player -->
<div class="video-section">
<div class="video-top-bar">
<div class="vtb-left">
<div class="live-dot">● LIVE STREAM</div>
</div>
<div class="vtb-right">
<button class="icon-btn" id="pipbtn" title="Picture in Picture"><i class="fas fa-clone"></i></button>
<button class="icon-btn" id="fsbtn" title="Fullscreen"><i class="fas fa-expand"></i></button>
</div>
</div>
<div class="vid-frame" id="vf">
<video id="vid" preload="auto" playsinline autoplay>
    <source src="/watch/{file_id}/{filename}" type="video/mp4">
</video>
<div class="vbuf" id="vbuf"><div class="buf-spin"></div></div>
<div class="cpop-w"><div class="cpop-ico" id="cpico"><i class="fas fa-play"></i></div></div>
<div class="ctrl" id="ctrl">
<div class="seekbar" id="seekbar">
<div class="sb-buf" id="sbbuf"></div>
<div class="sb-p" id="sbp"></div>
<div class="sb-thumb" id="sbth"></div>
<div class="sb-tip" id="sbtip">0:00</div>
</div>
<div class="ctrl-row">
<button class="cb" id="pbtn"><i class="fas fa-play"></i></button>
<button class="cb" id="bbtn"><i class="fas fa-backward-step"></i><span style="font-size:9px">10</span></button>
<button class="cb" id="fbtn"><i class="fas fa-forward-step"></i><span style="font-size:9px">10</span></button>
<div class="vol-g">
<button class="cb" id="mbtn"><i class="fas fa-volume-high"></i></button>
<input type="range" class="vol-r" id="volr" min="0" max="1" step="0.02" value="1">
</div>
<span class="t-disp" id="tdisp">0:00 / 0:00</span>
<div style="margin-left:auto;display:flex;align-items:center;gap:2px;position:relative">
<button class="cb" id="spdbtn">1×</button>
<div class="spop" id="spop">
<div class="si" data-s="0.25">0.25×</div>
<div class="si" data-s="0.5">0.5×</div>
<div class="si" data-s="0.75">0.75×</div>
<div class="si sel" data-s="1">1×</div>
<div class="si" data-s="1.25">1.25×</div>
<div class="si" data-s="1.5">1.5×</div>
<div class="si" data-s="2">2×</div>
</div>
</div>
</div>
</div>
</div>
</div>
<!-- Info Card -->
<div class="info-card">
<div class="info-left">
<div class="info-fname" id="pfname">{filename}</div>
<div class="info-tags">
<div class="tag tag-purple"><i class="fas fa-bolt"></i> Direct Stream</div>
<div class="tag tag-teal"><i class="fas fa-shield-halved"></i> Encrypted</div>
<div class="tag tag-blue" id="dur-tag"><i class="fas fa-clock"></i> Loading…</div>
</div>
</div>
<a id="dlbtn" href="/watch/{file_id}/{filename}" download class="btn-download">
<i class="fas fa-download"></i> Download File
</a>
</div>
<!-- Stats Row -->
<div class="stats-row">
<div class="stat-box">
<div class="stat-icon">⚡</div>
<div class="stat-val" style="color:var(--yellow)">Fast</div>
<div class="stat-lbl">Transfer</div>
</div>
<div class="stat-box">
<div class="stat-icon">🔒</div>
<div class="stat-val" style="color:var(--teal2)">E2E</div>
<div class="stat-lbl">Encrypted</div>
</div>
<div class="stat-box">
<div class="stat-icon">🎬</div>
<div class="stat-val" style="color:var(--purple2)">HD</div>
<div class="stat-lbl">Quality</div>
</div>
<div class="stat-box">
<div class="stat-icon">∞</div>
<div class="stat-val" style="color:var(--pink2)">None</div>
<div class="stat-lbl">Limits</div>
</div>
</div>
<!-- External Players -->
<div class="section-title">
<h2>Open in External Player</h2>
<span class="badge">HEVC · Multi-Audio</span>
</div>
<div class="players-grid">
<!-- VLC -->
<div class="player-card pc-vlc" onclick="openIn('vlc')">
<div class="app-icon" style="background:linear-gradient(145deg,#FF8C00,#E65000)">
<svg width="34" height="34" viewBox="0 0 100 100">
<polygon points="50,8 93,88 7,88" fill="rgba(255,255,255,.9)"/>
<rect x="32" y="64" width="36" height="20" rx="5" fill="#FF8C00"/>
<rect x="40" y="52" width="20" height="14" rx="3" fill="#FF8C00"/>
<circle cx="50" cy="40" r="13" fill="#FF8C00"/>
<circle cx="50" cy="40" r="5" fill="white"/>
</svg>
</div>
<div class="app-name">VLC Player</div>
<div class="app-feats">
<div class="app-feat"><i class="fas fa-check-circle"></i> HEVC / H.265</div>
<div class="app-feat"><i class="fas fa-check-circle"></i> All Codecs</div>
</div>
<button class="btn-open"><i class="fas fa-external-link-alt"></i> Open Now</button>
</div>
<!-- MX Player -->
<div class="player-card pc-mx" onclick="openIn('mx')">
<div class="app-icon" style="background:linear-gradient(145deg,#1976D2,#0D47A1)">
<svg width="34" height="34" viewBox="0 0 100 100">
<circle cx="50" cy="50" r="36" fill="rgba(255,255,255,.1)"/>
<polygon points="37,28 74,50 37,72" fill="white"/>
</svg>
</div>
<div class="app-name">MX Player</div>
<div class="app-feats">
<div class="app-feat"><i class="fas fa-check-circle"></i> Multi-Audio</div>
<div class="app-feat"><i class="fas fa-check-circle"></i> HW Decode</div>
</div>
<button class="btn-open"><i class="fas fa-external-link-alt"></i> Open Now</button>
</div>
<!-- PlayIt -->
<div class="player-card pc-pi" onclick="openIn('playit')">
<div class="app-icon" style="background:linear-gradient(145deg,#00B894,#007A60)">
<svg width="34" height="34" viewBox="0 0 100 100">
<circle cx="50" cy="50" r="36" fill="rgba(255,255,255,.1)"/>
<circle cx="50" cy="50" r="20" fill="rgba(255,255,255,.12)"/>
<polygon points="41,33 67,50 41,67" fill="white"/>
</svg>
</div>
<div class="app-name">PlayIt</div>
<div class="app-feats">
<div class="app-feat"><i class="fas fa-check-circle"></i> Fast Stream</div>
<div class="app-feat"><i class="fas fa-check-circle"></i> Smooth HW</div>
</div>
<button class="btn-open"><i class="fas fa-external-link-alt"></i> Open Now</button>
</div>
</div>

</div>
</div>
<!-- Toast -->
<div id="toast">
<div class="toast-icon-wrap" id="t-ico-wrap" style="background:rgba(255,140,0,.15)">
<span id="t-ico">🎬</span>
</div>
<div class="t-body">
<div class="t-title" id="t-title">Opening player…</div>
<div class="t-sub" id="t-sub">Install the app if it doesn't launch automatically.</div>
</div>
<button id="t-x" onclick="closeToast()"><i class="fas fa-xmark"></i></button>
</div>
<script>
const VIDEO_URL = "/watch/{file_id}/{filename}";
const CIRC = 2 * Math.PI * 80; // 502.65
/* ─── COUNTDOWN ─── */
document.getElementById("ps").classList.add("show");\ninitPlayer();\nfunction ss(id, cls) {{
const el = document.getElementById(id);
el.className = 'cd-step ' + cls;
}}
/* ─── PLAYER ─── */
const vid = document.getElementById('vid');
const vf = document.getElementById('vf');
const pbtn = document.getElementById('pbtn');
const bbtn = document.getElementById('bbtn');
const fbtn = document.getElementById('fbtn');
const mbtn = document.getElementById('mbtn');
const volr = document.getElementById('volr');
const tdisp = document.getElementById('tdisp');
const seekbar= document.getElementById('seekbar');
const sbbuf = document.getElementById('sbbuf');
const sbp = document.getElementById('sbp');
const sbth = document.getElementById('sbth');
const sbtip = document.getElementById('sbtip');
const spdbtn = document.getElementById('spdbtn');
const spop = document.getElementById('spop');
const pipbtn = document.getElementById('pipbtn');
const fsbtn = document.getElementById('fsbtn');
const vbuf = document.getElementById('vbuf');
const cpico = document.getElementById('cpico');
function fmt(s) {{
if (!s || isNaN(s)) return '0:00';
return `${{Math.floor(s/60)}}:${{String(Math.floor(s%60)).padStart(2,'0')}}`;
}}
function syncBtn() {{
pbtn.innerHTML = vid.paused ? '<i class="fas fa-play"></i>' : '<i class="fas fa-pause"></i>';
}}
function pop(t) {{
cpico.innerHTML = `<i class="fas fa-${{t==='play'?'play':'pause'}}"></i>`;
cpico.classList.remove('go'); void cpico.offsetWidth; cpico.classList.add('go');
}}
function toggle() {{
if (vid.paused) {{ vid.play(); pop('play'); }} else {{ vid.pause(); pop('pause'); }}
}}
function initPlayer() {{
vid.load();
setTimeout(() => vid.play().catch(() => {{}}), 200);
}}
// One-tap anywhere to force play if blocked by Chrome autoplay policy
let hasInteracted = false;
document.addEventListener('click', () => {{
    if (!hasInteracted) {{
        hasInteracted = true;
        if (vid.paused) vid.play().catch(() => {{}});
    }}
}}, {{once: true}});
document.addEventListener('touchstart', () => {{
    if (!hasInteracted) {{
        hasInteracted = true;
        if (vid.paused) vid.play().catch(() => {{}});
    }}
}}, {{once: true, passive: true}});

vid.addEventListener('play', syncBtn);
vid.addEventListener('pause', syncBtn);
vid.addEventListener('click', toggle);
pbtn.addEventListener('click', e => {{ e.stopPropagation(); toggle(); }});
bbtn.addEventListener('click', e => {{ e.stopPropagation(); vid.currentTime -= 10; }});
fbtn.addEventListener('click', e => {{ e.stopPropagation(); vid.currentTime += 10; }});
vid.addEventListener('timeupdate', () => {{
const p = vid.duration ? vid.currentTime / vid.duration * 100 : 0;
sbp.style.width = p + '%'; sbth.style.left = p + '%';
tdisp.textContent = fmt(vid.currentTime) + ' / ' + fmt(vid.duration);
}});
vid.addEventListener('progress', () => {{
if (vid.buffered.length && vid.duration)
sbbuf.style.width = (vid.buffered.end(vid.buffered.length-1) / vid.duration * 100) + '%';
}});
vid.addEventListener('loadedmetadata', () => {{
document.getElementById('dur-tag').innerHTML = `<i class="fas fa-clock"></i> ${{fmt(vid.duration)}}`;
}});
vid.addEventListener('waiting', () => vbuf.classList.add('on'));
vid.addEventListener('playing', () => vbuf.classList.remove('on'));
vid.addEventListener('canplay', () => vbuf.classList.remove('on'));
/* Seek */
let drag = false;
function seekTo(e) {{
const r = seekbar.getBoundingClientRect();
const x = Math.max(0, Math.min((e.touches?.[0]?.clientX ?? e.clientX) - r.left, r.width));
if (vid.duration) vid.currentTime = x / r.width * vid.duration;
}}
seekbar.addEventListener('mousedown', e => {{ drag=true; seekTo(e); }});
document.addEventListener('mousemove', e => {{ if(drag) seekTo(e); }});
document.addEventListener('mouseup', () => drag=false);
seekbar.addEventListener('touchstart', e => {{ drag=true; seekTo(e); }}, {{passive:true}});
document.addEventListener('touchmove', e => {{ if(drag) seekTo(e); }}, {{passive:true}});
document.addEventListener('touchend', () => drag=false);
seekbar.addEventListener('mousemove', e => {{
const r = seekbar.getBoundingClientRect();
const x = Math.max(0, Math.min(e.clientX - r.left, r.width));
sbtip.textContent = fmt(x / r.width * (vid.duration||0));
sbtip.style.left = (x / r.width * 100) + '%';
}});
/* Volume */
mbtn.addEventListener('click', e => {{
e.stopPropagation(); vid.muted = !vid.muted;
mbtn.innerHTML = vid.muted ? '<i class="fas fa-volume-xmark"></i>' : '<i class="fas fa-volume-high"></i>';
}});
volr.addEventListener('input', e => {{
e.stopPropagation(); vid.volume = volr.value; vid.muted = vid.volume === 0;
mbtn.innerHTML = (vid.volume===0||vid.muted) ? '<i class="fas fa-volume-xmark"></i>' : '<i class="fas fa-volume-high"></i>';
}});
/* Speed */
spdbtn.addEventListener('click', e => {{ e.stopPropagation(); spop.classList.toggle('on'); }});
spop.querySelectorAll('.si').forEach(el => {{
el.addEventListener('click', e => {{
e.stopPropagation();
vid.playbackRate = parseFloat(el.dataset.s);
spdbtn.textContent = el.dataset.s + '×';
spop.querySelectorAll('.si').forEach(i => i.classList.remove('sel'));
el.classList.add('sel'); spop.classList.remove('on');
}});
}});
document.addEventListener('click', () => spop.classList.remove('on'));
/* PiP */
pipbtn.addEventListener('click', async e => {{
e.stopPropagation();
try {{ document.pictureInPictureElement ? await document.exitPictureInPicture() : await vid.requestPictureInPicture(); }}
catch(_) {{}}
}});
/* Fullscreen */
fsbtn.addEventListener('click', e => {{
e.stopPropagation();
if (!document.fullscreenElement) {{
(vf.requestFullscreen || vf.webkitRequestFullscreen).call(vf);
fsbtn.innerHTML = '<i class="fas fa-compress"></i>';
}} else {{
(document.exitFullscreen || document.webkitExitFullscreen).call(document);
}}
}});
document.addEventListener('fullscreenchange', () => {{
if (!document.fullscreenElement) fsbtn.innerHTML = '<i class="fas fa-expand"></i>';
}});
/* Keyboard */
document.addEventListener('keydown', e => {{
if (['INPUT','TEXTAREA'].includes(document.activeElement.tagName)) return;
switch(e.code) {{
case 'Space': e.preventDefault(); toggle(); break;
case 'ArrowLeft': vid.currentTime -= 5; break;
case 'ArrowRight': vid.currentTime += 5; break;
case 'ArrowUp': vid.volume = Math.min(1,vid.volume+.1); volr.value=vid.volume; break;
case 'ArrowDown': vid.volume = Math.max(0,vid.volume-.1); volr.value=vid.volume; break;
case 'KeyM': mbtn.click(); break;
case 'KeyF': fsbtn.click(); break;
}}
}});
/* Auto-hide controls */
let ht;
function rh() {{
vf.classList.remove('hc'); clearTimeout(ht);
if (!vid.paused) ht = setTimeout(() => vf.classList.add('hc'), 3000);
}}
vf.addEventListener('mousemove', rh);
vf.addEventListener('touchstart', rh, {{passive:true}});
vid.addEventListener('play', () => {{ ht = setTimeout(() => vf.classList.add('hc'), 3000); }});
vid.addEventListener('pause', () => {{ vf.classList.remove('hc'); clearTimeout(ht); }});
/* ─── EXTERNAL PLAYERS ─── */
const APPS = {{
vlc: {{ ico:'🎬', bg:'rgba(255,140,0,.15)', t:'Opening VLC Player…', s:'VLC supports HEVC/H.265 & all audio codecs. Get it at videolan.org', u: x=>`vlc://${{x}}` }},
mx: {{ ico:'▶️', bg:'rgba(25,118,210,.15)', t:'Opening MX Player…', s:'MX Player supports multi-audio tracks & hardware decoding.', u: x=>`intent:${{x}}#Intent;package=com.mxtech.videoplayer.ad;end` }},
playit: {{ ico:'▶', bg:'rgba(0,184,148,.15)', t:'Opening PlayIt Player…', s:'PlayIt provides fast hardware-accelerated smooth playback.', u: x=>`intent:${{x}}#Intent;package=com.playit.videoplayer;end` }}
}};
function openIn(app) {{
const c = APPS[app];
window.location.href = c.u(encodeURIComponent(window.location.origin + VIDEO_URL));
document.getElementById('t-ico').textContent = c.ico;
document.getElementById('t-ico-wrap').style.background = c.bg;
document.getElementById('t-title').textContent = c.t;
document.getElementById('t-sub').textContent = c.s;
const t = document.getElementById('toast');
t.classList.add('show');
clearTimeout(window._tt);
window._tt = setTimeout(() => t.classList.remove('show'), 7000);
}}
function closeToast() {{ document.getElementById('toast').classList.remove('show'); }}
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
            
            # If file_size is missing (older movies), try to fetch it from the original message!
            if not file_size and movie.get('source_chat_id') and movie.get('source_message_id'):
                try:
                    msg = await self.client.get_messages(movie['source_chat_id'], movie['source_message_id'])
                    if msg:
                        if msg.video:
                            file_size = msg.video.file_size
                        elif msg.document:
                            file_size = msg.document.file_size
                        
                        # Save it back to db so we don't have to fetch it next time
                        if file_size:
                            await movies_col.update_one({'_id': movie['_id']}, {'$set': {'file_size': file_size}})
                except Exception:
                    pass
            
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
            
            # Determine correct mime type so browsers properly demux MKV audio (AAC)
            fake_mp4 = request.query.get('fake_mp4')
            if fake_mp4 == 'true' or filename.lower().endswith('.mkv'):
                # Force mp4 for mkv files to allow Chrome to sniff and demux AAC audio properly
                mime_type = 'video/mp4'
            else:
                mime_type, _ = mimetypes.guess_type(filename)
                mime_type = mime_type or 'video/mp4'
                
            headers = {
                'Content-Type': mime_type,
                'Accept-Ranges': 'bytes',
                'Content-Disposition': f'inline; filename="{filename}"',
                'Cross-Origin-Resource-Policy': 'cross-origin',
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Methods': 'GET, HEAD, OPTIONS',
                'Access-Control-Allow-Headers': 'Range, Accept, Content-Type'
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
            bytes_left = length if length > 0 else float('inf')
            
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
