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
from typing import Optional, List
import re
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pymongo import MongoClient, TEXT
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

# Funktion, die sicherstellt, dass ein Text-Index existiert
# Wir überprüfen vorhandene Indizes und erstellen/überschreiben nur, wenn über env var angefordert.
TEXT_INDEX_NAME = os.getenv("TEXT_INDEX_NAME", "text")
TEXT_INDEX_OVERWRITE = os.getenv("TEXT_INDEX_OVERWRITE", "false").lower() in ("1", "true", "yes")
TEXT_INDEX_WEIGHTS = {"title": 5, "alt": 2, "transcript": 1}
TEXT_INDEX_DEFAULT_LANGUAGE = os.getenv("TEXT_INDEX_DEFAULT_LANGUAGE", "english")

def _ensure_text_index():
    indexes = collection.index_information()
    existing_text_index = None
    # Prüfe, ob bereits ein Text-Index existiert
    for name, info in indexes.items():
        for key, typ in info.get("key", []):
            if typ == "text":
                existing_text_index = name
                break
        if existing_text_index:
            break

    if existing_text_index:
        if TEXT_INDEX_OVERWRITE:
            print(f"Dropping existing text index '{existing_text_index}' and recreating as '{TEXT_INDEX_NAME}'")
            collection.drop_index(existing_text_index)
        else:
            print(f"Text index already exists ('{existing_text_index}'), not recreating. Set TEXT_INDEX_OVERWRITE=1 to force.")
            return

    # Index fehlt oder wird überschrieben:
    print(f"Creating text index '{TEXT_INDEX_NAME}' (fields: title, alt, transcript)")
    collection.create_index(
        [("title", TEXT), ("alt", TEXT), ("transcript", TEXT)],
        name=TEXT_INDEX_NAME,
        weights=TEXT_INDEX_WEIGHTS,
        default_language=TEXT_INDEX_DEFAULT_LANGUAGE,
    )

# Text Index sicherstellen
_ensure_text_index()

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
        # Entferne evtl. Text-Score Metadaten, die bei $text-Projektion zurückkommen können
        doc.pop("score", None)
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
    q: List[str] = Query(..., min_length=1, description="Suchbegriffe; mehrfach erlaubt (z.B. ?q=foo&q=bar)"),
    limit: int = Query(20, ge=1, le=100, description="Max. Ergebnisse")
):
    """
    Stichwortsuche in Comics (Titel, Alt-Text, Transcript).
    """
    # Verwende MongoDB $text-Suche über die vorher angelegte Text-Index
    # q kann mehrfach übergeben werden (z.B. ?q=foo&q=bar) und wird zu einem Suchstring kombiniert.
    # Beispiel: q=["foo", "bar"] -> search_string="foo bar"
    search_string = " ".join(q)
    # Projektiere den textScore und sortiere danach
    cursor = collection.find(
        {"$text": {"$search": search_string}},
        {"score": {"$meta": "textScore"}}
    ).sort([("score", {"$meta": "textScore"})]).limit(limit)

    results = list(cursor)
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