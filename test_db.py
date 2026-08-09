from pymongo import MongoClient
import os

uri = "mongodb+srv://dharani2006lakshmi_db_user:Byi5WDiKV6H53Xe1@cluster0.p93dbly.mongodb.net"
client = MongoClient(uri)
db = client['cinesearch_db']
collection = db['movies']

movie = collection.find_one()
print(movie)
