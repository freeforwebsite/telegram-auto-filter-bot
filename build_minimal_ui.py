import re

with open('stream_server/server.py', 'r', encoding='utf-8') as f:
    server_code = f.read()

new_html = """
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
            <video id="player" playsinline controls>
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

new_code = re.sub(r'html_content = f"""(.*?)"""\n\s*return web\.Response', 
                  'html_content = f"""' + new_html + '"""\n        return web.Response', 
                  server_code, 
                  flags=re.DOTALL)

with open('stream_server/server.py', 'w', encoding='utf-8') as f:
    f.write(new_code)
