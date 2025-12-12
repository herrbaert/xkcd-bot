import os
import requests
from dotenv import load_dotenv
from pymongo import MongoClient
import time
import argparse

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

    data = resp.json()
    for key in ["year", "month", "day"]:
        try:
            data[key] = int(data.get(key, '0'))
        except ValueError:
            data[key] = None

    return data

def save_comic(doc):
    collection.update_one(
        {"num": doc["num"]},
        {"$set": doc},
        upsert=True
    )

def download_comics(start: int = 1, end: int | None = None, resume: bool = True, delay: float = 0.5):
    """Download loop: lade Comics von `start` bis `end` (inkl.) und speichere sie in der DB.

    - Wenn `end` None ist, wird die neueste Comic-Nummer verwendet.
    - Wenn `resume` True ist, werden bereits vorhandene Einträge übersprungen.
    - `delay` gibt Sekunden Pause zwischen Requests an (Rate-limiting / Höflichkeit).
    """
    if end is None:
        end = get_latest_comic_number()

    print(f"Downloading comics {start}..{end} (resume={resume}, delay={delay}s)")
    for num in range(start, end + 1):
        try:
            if resume and collection.find_one({"num": num}):
                print(f"{num}: already in DB, skipping")
                continue

            comic = fetch_comic(num)
        except Exception as exc:
            print(f"{num}: error during fetch: {exc}")
            continue

        if not comic:
            print(f"{num}: not found or unavailable, skipping")
            continue

        try:
            save_comic(comic)
            print(f"{num}: saved to DB")
        except Exception as exc:
            print(f"{num}: error saving to DB: {exc}")

        time.sleep(delay)

def test():
    latest_comic_number = get_latest_comic_number()
    print(latest_comic_number)
    latest_comic = fetch_comic(latest_comic_number)
    print(latest_comic)

    response = input("Möchtest du den Comic speichern? (j/n): ")
    if response.lower() == 'j':
        save_comic(latest_comic)
        print("Comic gespeichert.")
    else:
        print("Comic nicht gespeichert.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="xkcd scraper")
    parser.add_argument("--download", action="store_true", help="Download a range of comics into the DB")
    parser.add_argument("--start", type=int, default=1, help="Start comic number (inclusive)")
    parser.add_argument("--end", type=int, help="End comic number (inclusive). If omitted, uses latest comic")
    parser.add_argument("--no-resume", dest="resume", action="store_false", help="Do not skip comics already in DB")
    parser.add_argument("--delay", type=float, default=0.5, help="Delay in seconds between requests")
    args = parser.parse_args()

    print("Setup fertig!")
    if args.download:
        download_comics(start=args.start, end=args.end, resume=args.resume, delay=args.delay)
    else:
        test()