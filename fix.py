import re

with open('dump.html', 'r', encoding='utf-8') as f:
    html = f.read()

# Escape all braces for f-string
html = html.replace('{', '{{').replace('}', '}}')

# Unescape our specific variables
html = html.replace('{{filename}}', '{filename}')
html = html.replace('{{file_id}}', '{file_id}')

# Replace the title and file name
html = html.replace('LoveToRide | Dhurandhar The Revenge Raw and Undekha 2026 720p 10bit WEBRip TAMiL.mkv', 'Watch: {filename}')
html = html.replace('Dhurandhar The Revenge Raw and Undekha 2026 720p 10bit WEBRip TAMiL.mkv', '{filename}')

# Replace the redirect URL
html = html.replace('https://files.tglink.space/get_temp_link?url=https://files.tglink.space/watch/5328345/Dhurandhar_The_Revenge_Raw_and_Undekha_2026_720p_10bit_WEBRip_TAMiL.mkv?hash=AgADCR', '/watch/{file_id}/{filename}')

# Replace Join Channel Link
html = html.replace('https://t.me/+6eWQ0W8Q5xEyMDM0', 'https://t.me/MoviiWrld')

# Add video player logic!
# We will append the Plyr CSS/JS and the video container
video_html = """
    <div id='player-wrapper' style='display: none; width: 100%; max-width: 420px; border-radius: 12px; overflow: hidden; box-shadow: 0 10px 30px rgba(0,0,0,0.5); background: #000; margin-bottom: 14px;'>
        <video id='player' playsinline controls>
            <source src='/watch/{file_id}/{filename}' type='video/mp4' />
        </video>
    </div>
"""

html = html.replace('</head>', '<link rel="stylesheet" href="https://cdn.plyr.io/3.7.8/plyr.css" />\n</head>')
html = html.replace('<!-- Telegram Channel Card -->', video_html + '\n    <!-- Telegram Channel Card -->')
html = html.replace('</body>', '<script src="https://cdn.plyr.io/3.7.8/plyr.js"></script>\n<script>const player = new Plyr(\'#player\');</script>\n</body>')

# Change the button click behavior to show the player AND download link
old_js = "setTimeout(() => {{ window.location.href = '/watch/{file_id}/{filename}'; }}, 800);"
new_js = """setTimeout(() => {{ 
            document.getElementById('player-wrapper').style.display = 'block'; 
            document.getElementById('download-btn').textContent = 'Scroll up to Watch or Click to Download'; 
            downloadBtn.onclick = () => {{ window.location.href = '/watch/{file_id}/{filename}'; }}; 
          }}, 800);"""
html = html.replace(old_js, new_js)

# Now write this to server.py
with open('stream_server/server.py', 'r', encoding='utf-8') as f:
    server_py = f.read()

# We need to replace html_content = f\"\"\" ... \"\"\" with our new HTML
new_server_py = re.sub(r'html_content = f\"\"\"(.*?)\"\"\"', 'html_content = f\"\"\"\\n' + html + '\\n        \"\"\"', server_py, flags=re.DOTALL)

with open('stream_server/server.py', 'w', encoding='utf-8') as f:
    f.write(new_server_py)
