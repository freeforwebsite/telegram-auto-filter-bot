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

def search_omdb(title):
    if not title:
        return None
        
    OMDB_API_KEY = os.environ.get("OMDB_API_KEY", "3bc5f75d") # Use env or fallback key
    url = f"http://www.omdbapi.com/"
    params = {
        "apikey": OMDB_API_KEY,
        "t": title,
    }
    
    try:
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        
        if data.get("Response") == "True":
            return data
                
        # If no results, try removing the last word (often helps if title is messy)
        words = title.split()
        if len(words) > 1:
            shorter_title = " ".join(words[:-1])
            return search_omdb(shorter_title) # Recursive fallback
            
    except Exception as e:
        print(f"OMDB API Error for '{title}': {e}")
        
    return None

def start_enricher():
    print("Starting OMDB Enricher Background Worker...")
    
    while True:
        try:
            # Find movies that haven't been processed by TMDB/OMDB yet
            movie = movies_collection.find_one({
                "tmdb_processed": {"$exists": False}
            })
            
            if not movie:
                print("✅ All movies enriched! Sleeping for 60 seconds...")
                time.sleep(60)
                continue
                
            original_filename = movie.get("file_name", "")
            clean_title = clean_movie_title(original_filename)
            
            print(f"\n🔄 Processing: {original_filename}")
            print(f"🔍 Searching OMDB for: '{clean_title}'")
            
            omdb_data = search_omdb(clean_title)
            
            if omdb_data:
                poster_url = omdb_data.get("Poster")
                if poster_url == "N/A":
                    poster_url = None
                    
                rating = omdb_data.get("imdbRating")
                try:
                    rating = float(rating) if rating != "N/A" else 0.0
                except:
                    rating = 0.0
                
                rich_data = {
                    "tmdb_id": omdb_data.get("imdbID"), # using imdbID to maintain schema compatibility
                    "tmdb_type": "movie" if omdb_data.get("Type") == "movie" else "tv",
                    "title": omdb_data.get("Title"),
                    "overview": omdb_data.get("Plot") if omdb_data.get("Plot") != "N/A" else "No description available.",
                    "release_date": omdb_data.get("Released") if omdb_data.get("Released") != "N/A" else omdb_data.get("Year"),
                    "rating": rating,
                    "poster_url": poster_url,
                    "backdrop_url": poster_url, # OMDB doesn't have backdrops, fallback to poster
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
                print(f"❌ Not found on OMDB.")
                
            # Sleep 1 second to respect rate limits
            time.sleep(1)
            
        except Exception as e:
            print(f"Worker crashed: {e}")
            time.sleep(5)

if __name__ == "__main__":
    start_enricher()
