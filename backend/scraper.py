"""
xkcd-bot scraper

Dieses Modul lädt xkcd-Comics (JSON-Metadaten) herunter und speichert sie in einer MongoDB.

Big picture:
- Konfiguration: Umgebungsvariablen (MONGO_URI, MONGO_DB, MONGO_COLLECTION) werden über eine .env-Datei geladen.
- Verbindung: Eine MongoDB-Verbindung wird aufgebaut und eine Collection referenziert.
- Funktionalität:
  - `get_latest_comic_number`: Fragt die neueste Comic-Nummer bei xkcd ab.
  - `fetch_comic`: Lädt die JSON-Metadaten für ein bestimmtes Comic herunter und bereinigt Datumsfelder.
  - `save_comic`: Speichert oder aktualisiert einen Comic-Eintrag in der DB.
  - `download_comics`: Haupt-Download-Loop, lädt einen Bereich von Comics herunter und speichert sie (mit replace/Delay).
  - `test`: Interaktiver Schnelltest für ein einzelnes Comic (nur zum Entwickeln).
- CLI: Das Script kann als CLI mit Argumenten aufgerufen werden, z.B. um einen Bereich herunterzuladen.

Hinweis zur Nutzung:
- Stelle sicher, dass die .env-Datei die benötigten MongoDB-Variablen enthält.
- Beim ersten Lauf kann `--download` mit `--start`/`--end` genutzt werden; Standard-Delay ist gesetzt, um die xkcd-Server nicht zu überlasten.

"""

# Standardimporte: os für Umgebungsvariablen, requests für HTTP-Requests, dotenv zum Laden der .env,
# pymongo zum Zugriff auf die MongoDB. time für Pausen zwischen Requests, argparse für CLI.
import os
import requests
from dotenv import load_dotenv
from pymongo import MongoClient
import time
import argparse
import sys

# .env laden (Pfad hier ist relativ zum Projekt; kann angepasst werden)
load_dotenv()

# Konfigurationswerte aus der Umgebung lesen
MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB = os.getenv("MONGO_DB")
MONGO_COLLECTION = os.getenv("MONGO_COLLECTION")

# Sicherheitsprüfung: Ohne diese Variablen macht das Programm keinen Sinn
if not (MONGO_URI and MONGO_DB and MONGO_COLLECTION):
    raise RuntimeError("Required env vars missing: MONGO_URI, MONGO_DB, MONGO_COLLECTION")

# MongoDB-Client initialisieren und die gewählte Collection referenzieren.
# Die Verbindung bleibt während der Laufzeit offen; das ist für kleine Scraper-Tasks in Ordnung.
client = MongoClient(MONGO_URI)
db = client[MONGO_DB]
collection = db[MONGO_COLLECTION]


def get_latest_comic_number() -> int:
    """Hole die aktuellste Comic-Nummer von xkcd.

    Rückgabewert:
    - int: Die aktuelle höchste Comic-Nummer.

    Fehler/Edgecases:
    - Wir werfen eine RuntimeError, wenn keine gültige Nummer aus der API zurückkommt.
    - Die Funktion führt ein einfaches HTTP-GET aus; bei Netzwerkproblemen wird eine Exception von
      requests nach außen propagiert (kann vom Aufrufer gefangen werden).
    """
    resp = requests.get("https://xkcd.com/info.0.json")
    data = resp.json()
    num = data["num"]
    if not num or not isinstance(num, int):
        # defensive Prüfung: API sollte eine gültige Nummer liefern
        raise RuntimeError("Could not get latest comic number")
    return num


def fetch_comic(num):
    """Lade die JSON-Metadaten für ein einzelnes xkcd-Comic.

    Parameter:
    - num: Comic-Nummer (int)

    Verhalten:
    - Baut die URL zusammen und führt einen GET-Request aus.
    - Wenn der Statuscode != 200 ist, wird None zurückgegeben (Comic nicht vorhanden oder Fehler).
    - Konvertiert die Strings für year/month/day in Integers, oder setzt sie auf None bei ungültigen Werten.

    Rückgabewert:
    - dict: Die JSON-Daten des Comics (z.B. keys: num, title, img, alt, year, month, day, ...)
    - None: Wenn das Comic nicht gefunden wurde (HTTP != 200)

    Hinweise zur Robustheit:
    - Die Funktion geht davon aus, dass die API ein erwartetes Schema liefert. Sollte die Struktur
      sich ändern, kann es zu KeyError/ValueError kommen. Der Aufrufer kann Exceptions behandeln.
    """
    url = f"https://xkcd.com/{num}/info.0.json"
    resp = requests.get(url)

    if resp.status_code != 200:
        # z.B. 404 für fehlende Comics (manche Nummern fehlen) oder 403/5xx bei Problemen
        return None

    data = resp.json()
    # xkcd liefert year/month/day als Strings; wir wandeln sie zu int oder None um.
    for key in ["year", "month", "day"]:
        try:
            data[key] = int(data.get(key, '0'))
        except ValueError:
            data[key] = None

    return data


def save_comic(doc):
    """Speichere oder aktualisiere einen Comic-Datensatz in der MongoDB-Collection.

    Verhalten:
    - Upsert: Wenn ein Dokument mit der gleichen `num` existiert, wird es aktualisiert,
      ansonsten wird ein neues Dokument angelegt.

    Hinweise:
    - Diese Funktion verwendet ein einfaches update_one mit $set; bei Bedarf können weitere
      Feld-begrenzungen oder Validierungen ergänzt werden.
    """
    collection.update_one(
        {"num": doc["num"]},
        {"$set": doc},
        upsert=True
    )


def get_highest_stored_comic_number() -> int:
    doc = collection.find_one(sort=[("num", -1)])
    if doc:
        return doc["num"]
    return 0

def get_all_stored_comic_numbers() -> list[int]:
    return [doc["num"] for doc in collection.find({}, {"num": 1})]

def get_all_comics_without_transcript() -> list[int]:
    comic_nums = [doc["num"] for doc in collection.find({"transcript": {"$in": [None, ""]}}, {"num": 1})]
    return comic_nums

def get_transcript_for_comic(num: int) -> str:
    """Hole das Transcript für ein xkcd-Comic von explainxkcd.com.

    Verhalten:
    - Ruft die Wiki-Seite für das Comic auf explainxkcd.com auf
    - Sucht nach dem Element mit id="Transcript"
    - Extrahiert den Text aus den folgenden Sibling-Elementen

    Parameter:
    - num: Comic-Nummer (int)

    Rückgabewert:
    - str: Das Transcript-Text oder leerer String wenn nicht gefunden
    """
    try:
        from bs4 import BeautifulSoup, Tag

        base_url = f"https://www.explainxkcd.com/wiki/index.php/{num}"
        resp = requests.get(base_url, timeout=10)

        if resp.status_code != 200:
            return ""

        soup = BeautifulSoup(resp.content, 'html.parser')

        # Suche das Element mit id="Transcript"
        transcript_heading = soup.find(id="Transcript")

        if not transcript_heading:
            return ""

        # Das Element mit id="Transcript" ist ein <span> innerhalb eines <h2>
        # Wir müssen das <h2> (Eltern-Element) finden
        h2_element = transcript_heading.find_parent('h2')

        if not h2_element:
            return ""

        # Hole das nächste Sibling-Element nach dem <h2>
        # Dies sollte das <dl>-Element mit den <dd>-Einträgen sein oder ein <p> oder anderes Element
        transcript = ""
        current_element = h2_element.find_next_sibling()

        def is_headline(element: Tag) -> bool:
            children = element.find_all(recursive=False)
            for test in [element, *children]:
                class_list = test.get('class')
                if class_list and "mw-headline" in class_list:
                # if test.get('id') in ["Trivia", "Discussion"]:
                    return True
            return False

        while current_element and not is_headline(current_element):
            text = current_element.get_text(separator="", strip=True)
            if text:
                html = str(current_element)
                transcript += html
            current_element = current_element.find_next_sibling()

        # Füge alle Teile zusammen
        return transcript.strip()

    except Exception as exc:
        print(f"Error fetching transcript for comic {num}: {exc}")
        return ""

def add_transcript_to_comic(num: int, transcript: str):
    collection.update_one(
        {"num": num},
        {"$set": {"transcript": transcript}}
    )

def add_transcripts(replace: bool = False, comics: list[int] | None = None, start: int | None = None, end: int | None = None):
    if comics is None:
        if not replace:
            comics = get_all_comics_without_transcript()
        else:
            comics = get_all_stored_comic_numbers()
        if start is not None:
            comics = [num for num in comics if num >= start]
        if end is not None:
            comics = [num for num in comics if num <= end]
    print(f"Found {len(comics)} comics")
    for num in comics:
        transcript = get_transcript_for_comic(num)
        if transcript:
            add_transcript_to_comic(num, transcript)
            print(f"Added transcript to comic {num}")
        else:
            print(f"No transcript found for comic {num}")

def download_comics(
        start: int | None = None,
        end: int | None = None,
        replace: bool = True,
        delay: float | None = None
    ):
    """Haupt-Download-Loop: lade Comics im Bereich [start, end] und speichere sie in der DB.

    Parameter:
    - start: Startnummer (inklusive). Standard 1.
    - end: Endnummer (inklusive). Wenn None, wird die derzeit höchste Comic-Nummer verwendet.
    - replace: Wenn True, werden bereits vorhandene Comics in der DB übersprungen (nützlich beim Fortsetzen).
    - delay: Pause in Sekunden zwischen Requests, um Server nicht zu überlasten.

    Verhalten/Strategie:
    - Bestimmt bei Bedarf zuerst die neueste Comic-Nummer.
    - Iteriert über die Zahlenreihe und versucht für jede Nummer:
      1. Bei replace: prüfen, ob bereits ein Dokument existiert, dann skippen.
      2. fetch_comic aufrufen; bei HTTP-Fehlern oder None wird übersprungen.
      3. save_comic aufrufen, Fehler beim Speichern werden geloggt, aber die Schleife läuft weiter.
    - Kleine Pausen (delay) zwischen Requests helfen, Rate-Limits und Last zu vermeiden.

    Robustheit:
    - Fehler beim Fetch oder Speichern fangen wir pro-Comic ab, so dass ein Einzelfehler die
      gesamte Operation nicht stoppt.
    """

    if start is None:
        start = get_highest_stored_comic_number() + 1
    if end is None:
        end = get_latest_comic_number()
    if delay is None:
        delay = 0.3

    print(f"Processing comics {start} - {end} (replace = {replace}, delay = {delay}s)")
    for num in range(start, end + 1):
        try:
            if not replace and collection.find_one({"num": num}):
                print(f"{num}: already in DB, skipping")
                continue

            comic = fetch_comic(num)
        except Exception as exc:
            # Netzwerkfehler oder andere Exceptions beim Holen behandeln und weiterfahren
            print(f"{num}: error during fetch: {exc}")
            continue

        if not comic:
            # Comic nicht vorhanden (404) o.ä. - überspringen
            print(f"{num}: not found or unavailable, skipping")
            continue

        # if "transcript" not in comic or comic["transcript"] in [None, ""]:
        comic["transcript"] = get_transcript_for_comic(num)

        try:
            save_comic(comic)
            print(f"{num}: saved to DB")
        except Exception as exc:
            # Fehler beim Speichern (z.B. DB-Verbindung verloren) protokollieren
            print(f"{num}: error saving to DB: {exc}")

        # Kleine Pause zwischen den Anfragen
        time.sleep(delay)


if __name__ == "__main__":
    # Bugfix für VSCode Python Debugger, welcher:
    if len(sys.argv) == 2 and " " in sys.argv[1]:
        sys.argv = [sys.argv[0]] + sys.argv[1].split()
    parser = argparse.ArgumentParser(description="xkcd scraper")
    parser.add_argument("--start", type=int, help="Start comic number (inclusive). If omitted, uses next after highest in DB")
    parser.add_argument("--end", type=int, help="End comic number (inclusive). If omitted, uses latest comic")
    parser.add_argument("--replace", dest="replace", action="store_true", help="Skip comics already in DB")
    parser.add_argument("--delay", type=float, help="Delay in seconds between requests")
    parser.add_argument("--update", action="store_true", help="Fetch and add transcripts from explainxkcd.com")
    args = parser.parse_args()

    print("Setup fertig!")
    # print(args)

    # Download-Loop mit den übergebenen Optionen starten
    if args.update:
        add_transcripts(replace=args.replace, start=args.start, end=args.end)
    else:
        download_comics(start=args.start, end=args.end, replace=args.replace, delay=args.delay)