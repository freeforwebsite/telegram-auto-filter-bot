import os
import re
import time
import requests
import pymongo
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
MONGODB_URI = os.environ.get("MONGODB_URI", "")
TMDB_API_KEY = "74683f7b34f7b689d84fcd8e0016d82a"

print("Connecting to MongoDB...")
client = pymongo.MongoClient(MONGODB_URI)
db = client['telegram_bot']
movies_collection = db['movies']

def clean_movie_title(filename):
    """
    Strips out resolution, quality, codecs, and language tags 
    to extract a clean movie title for TMDB search.
    """
    # Remove file extension
    name = re.sub(r'\.(mkv|mp4|avi|webm)$', '', filename, flags=re.IGNORECASE)
    
    # Common release tags to remove
    tags = [
        r'1080p', r'720p', r'480p', r'2160p', r'4k',
        r'x264', r'x265', r'hevc', r'avc', r'10bit', r'hdr',
        r'webrip', r'web-dl', r'hdrip', r'bluray', r'brrip', r'dvdrip', r'hdtv', r'web', r'dl',
        r'tamil', r'telugu', r'hindi', r'malayalam', r'kannada', r'english',
        r'multi', r'audio', r'dual', r'sub', r'esub', r'msub',
        r'untouched', r'esubs', r'hq', r'line', r'predvd', r'nf', r'ta',
        r'\[.*?\]', r'\(.*?\)' # Remove brackets and parentheses
    ]
    
    for tag in tags:
        name = re.sub(tag, '', name, flags=re.IGNORECASE)
        
    # Replace dots, underscores, and dashes with spaces
    name = re.sub(r'[\._\-]', ' ', name)
    
    # Remove extra whitespace
    name = re.sub(r'\s+', ' ', name).strip()
    
    # Special fix for @channel tags or web links
    name = re.sub(r'@\w+', '', name)
    name = re.sub(r't me.*', '', name, flags=re.IGNORECASE)
    
    # Try to extract just the title before a year if present
    # e.g. "Spider Man 2002" -> "Spider Man"
    year_match = re.search(r'\b(19\d{2}|20\d{2})\b', name)
    year = None
    if year_match:
        year = year_match.group(1)
        # We can keep the year for TMDB search as it helps accuracy,
        # but sometimes it's better without it. Let's keep it for now.
        
    return name.strip()

def search_tmdb(title):
    if not title:
        return None
        
    url = f"https://api.themoviedb.org/3/search/multi"
    params = {
        "api_key": TMDB_API_KEY,
        "query": title,
        "include_adult": "false",
        "language": "en-US",
        "page": 1
    }
    
    try:
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        
        if data.get("results") and len(data["results"]) > 0:
            # Get the first result (most relevant)
            # Filter out person results (actors)
            valid_results = [r for r in data["results"] if r.get("media_type") in ["movie", "tv"]]
            
            if valid_results:
                return valid_results[0]
                
        # If no results, try removing the last word (often helps if title is messy)
        words = title.split()
        if len(words) > 1:
            shorter_title = " ".join(words[:-1])
            return search_tmdb(shorter_title) # Recursive fallback
            
    except Exception as e:
        print(f"TMDB API Error for '{title}': {e}")
        
    return None

def start_enricher():
    print("🎬 Starting TMDB Enricher Background Worker...")
    
    while True:
        try:
            # Find movies that haven't been processed by TMDB yet
            # Also find movies where tmdb_processed exists but is False (meaning previous failure)
            # We prioritize movies that don't even have the field.
            movie = movies_collection.find_one({
                "tmdb_processed": {"$exists": False}
            })
            
            if not movie:
                # If all are processed, try the ones that failed previously (maybe API was down)
                # But let's just sleep instead to prevent infinite failure loops
                print("✅ All movies enriched! Sleeping for 60 seconds...")
                time.sleep(60)
                continue
                
            original_filename = movie.get("file_name", "")
            clean_title = clean_movie_title(original_filename)
            
            print(f"\n🔄 Processing: {original_filename}")
            print(f"🔍 Searching TMDB for: '{clean_title}'")
            
            tmdb_data = search_tmdb(clean_title)
            
            if tmdb_data:
                # Build rich metadata object
                base_img_url = "https://image.tmdb.org/t/p/w500"
                base_bg_url = "https://image.tmdb.org/t/p/original"
                
                poster_path = tmdb_data.get("poster_path")
                backdrop_path = tmdb_data.get("backdrop_path")
                
                rich_data = {
                    "tmdb_id": tmdb_data.get("id"),
                    "tmdb_type": tmdb_data.get("media_type"),
                    "title": tmdb_data.get("title") or tmdb_data.get("name"),
                    "overview": tmdb_data.get("overview"),
                    "release_date": tmdb_data.get("release_date") or tmdb_data.get("first_air_date"),
                    "rating": tmdb_data.get("vote_average"),
                    "poster_url": f"{base_img_url}{poster_path}" if poster_path else None,
                    "backdrop_url": f"{base_bg_url}{backdrop_path}" if backdrop_path else None,
                    "tmdb_processed": True,
                    "tmdb_found": True
                }
                
                movies_collection.update_one(
                    {"_id": movie["_id"]},
                    {"$set": rich_data}
                )
                print(f"✅ Found! -> {rich_data['title']} (Rating: {rich_data['rating']})")
                
            else:
                # Mark as processed so we don't try again indefinitely
                movies_collection.update_one(
                    {"_id": movie["_id"]},
                    {"$set": {"tmdb_processed": True, "tmdb_found": False}}
                )
                print(f"❌ Not found on TMDB.")
                
            # Sleep 1 second to respect TMDB rate limits (max 40 requests per 10 seconds)
            time.sleep(1)
            
        except Exception as e:
            print(f"Worker crashed: {e}")
            time.sleep(5)

if __name__ == "__main__":
    start_enricher()
