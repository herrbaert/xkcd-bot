import os
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv('./.env')

MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB = os.getenv("MONGO_DB")
MONGO_COLLECTION = os.getenv("MONGO_COLLECTION")

if not (MONGO_URI and MONGO_DB and MONGO_COLLECTION):
    raise RuntimeError("Required env vars missing: MONGO_URI, MONGO_DB, MONGO_COLLECTION")

client = MongoClient(MONGO_URI)
db = client[MONGO_DB]
collection = db[MONGO_COLLECTION]

def get_latest_comic_number():
    resp = requests.get("https://xkcd.com/info.0.json")
    data = resp.json()
    return data["num"]

def fetch_comic(num):
    url = f"https://xkcd.com/{num}/info.0.json"
    resp = requests.get(url)

    if resp.status_code != 200:
        return None

    return resp.json()

def save_comic(doc):
    collection.update_one(
        {"num": doc["num"]},
        {"$set": doc},
        upsert=True
    )

if __name__ == "__main__":
    print("Setup fertig!")
