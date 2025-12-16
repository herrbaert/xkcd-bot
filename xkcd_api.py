"""
xkcd-bot API - MVP

Minimales FastAPI-Backend für die Stichwortsuche in xkcd-Comics.

Endpoints:
- GET /comics/search?q=keyword - Stichwortsuche
- GET /comics/{num} - Spezifisches Comic

Anforderungen:
- fastapi
- uvicorn
- pymongo
- python-dotenv
"""

import os
from typing import Optional
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pymongo import MongoClient
from dotenv import load_dotenv

# .env laden
load_dotenv()

# Konfiguration
MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB = os.getenv("MONGO_DB")
MONGO_COLLECTION = os.getenv("MONGO_COLLECTION")

if not (MONGO_URI and MONGO_DB and MONGO_COLLECTION):
    raise RuntimeError("Required env vars missing: MONGO_URI, MONGO_DB, MONGO_COLLECTION")

# MongoDB-Verbindung
client = MongoClient(MONGO_URI)
db = client[MONGO_DB]
collection = db[MONGO_COLLECTION]

# FastAPI App
app = FastAPI(title="xkcd Comic API - MVP", version="0.1.0")

# CORS aktivieren (für Frontend)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def clean_comic(doc):
    """Entfernt MongoDB _id Feld."""
    if doc:
        doc.pop("_id", None)
    return doc


@app.get("/")
async def root():
    """API Info."""
    total = collection.count_documents({})
    return {
        "message": "xkcd Comic API - MVP",
        "total_comics": total
    }


@app.get("/comics/search")
async def search_comics(
    q: str = Query(..., min_length=2, description="Suchbegriff"),
    limit: int = Query(20, ge=1, le=100, description="Max. Ergebnisse")
):
    """
    Stichwortsuche in Comics (Titel, Alt-Text, Transcript).
    """
    # Suche in Titel, Alt-Text und Transcript
    query = {
        "$or": [
            {"title": {"$regex": q, "$options": "i"}},
            {"alt": {"$regex": q, "$options": "i"}},
            {"transcript": {"$regex": q, "$options": "i"}}
        ]
    }
    
    results = list(collection.find(query).sort("num", -1).limit(limit))
    comics = [clean_comic(doc) for doc in results]
    
    return {
        "query": q,
        "count": len(comics),
        "comics": comics
    }


@app.get("/comics/{num}")
async def get_comic(num: int):
    """
    Liefert ein spezifisches Comic nach Nummer.
    """
    comic = collection.find_one({"num": num})
    
    if not comic:
        raise HTTPException(status_code=404, detail=f"Comic #{num} nicht gefunden")
    
    return clean_comic(comic)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)