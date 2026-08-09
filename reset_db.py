import os
import pymongo
from dotenv import load_dotenv

load_dotenv('.env')
client = pymongo.MongoClient(os.environ.get('MONGODB_URI'))
db = client['telegram_bot']
queue = db['queue']

result = queue.update_many({'status': {'$in': ['processing', 'failed']}}, {'$set': {'status': 'pending'}})
print(f'Reset {result.modified_count} movies back to pending!')
