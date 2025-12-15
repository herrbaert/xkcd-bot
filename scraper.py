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
  - `download_comics`: Haupt-Download-Loop, lädt einen Bereich von Comics herunter und speichert sie (mit Resume/Delay).
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

# .env laden (Pfad hier ist relativ zum Projekt; kann angepasst werden)
load_dotenv('./.env')

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


def download_comics(start: int = 1, end: int | None = None, resume: bool = True, delay: float = 0.5):
    """Haupt-Download-Loop: lade Comics im Bereich [start, end] und speichere sie in der DB.

    Parameter:
    - start: Startnummer (inklusive). Standard 1.
    - end: Endnummer (inklusive). Wenn None, wird die derzeit höchste Comic-Nummer verwendet.
    - resume: Wenn True, werden bereits vorhandene Comics in der DB übersprungen (nützlich beim Fortsetzen).
    - delay: Pause in Sekunden zwischen Requests, um Server nicht zu überlasten.

    Verhalten/Strategie:
    - Bestimmt bei Bedarf zuerst die neueste Comic-Nummer.
    - Iteriert über die Zahlenreihe und versucht für jede Nummer:
      1. Bei resume: prüfen, ob bereits ein Dokument existiert, dann skippen.
      2. fetch_comic aufrufen; bei HTTP-Fehlern oder None wird übersprungen.
      3. save_comic aufrufen, Fehler beim Speichern werden geloggt, aber die Schleife läuft weiter.
    - Kleine Pausen (delay) zwischen Requests helfen, Rate-Limits und Last zu vermeiden.

    Robustheit:
    - Fehler beim Fetch oder Speichern fangen wir pro-Comic ab, so dass ein Einzelfehler die
      gesamte Operation nicht stoppt.
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
            # Netzwerkfehler oder andere Exceptions beim Holen behandeln und weiterfahren
            print(f"{num}: error during fetch: {exc}")
            continue

        if not comic:
            # Comic nicht vorhanden (404) o.ä. - überspringen
            print(f"{num}: not found or unavailable, skipping")
            continue

        try:
            save_comic(comic)
            print(f"{num}: saved to DB")
        except Exception as exc:
            # Fehler beim Speichern (z.B. DB-Verbindung verloren) protokollieren
            print(f"{num}: error saving to DB: {exc}")

        # Kleine Pause zwischen den Anfragen
        time.sleep(delay)


def test():
    """Einfacher interaktiver Test, der das neueste Comic lädt und nach Speicherung fragt.

    Diese Hilfsfunktion ist primär für Entwicklung/Debugging gedacht.
    """
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
    # CLI: einfache Argumente um Download-Loop zu steuern oder den Test auszuführen.
    parser = argparse.ArgumentParser(description="xkcd scraper")
    parser.add_argument("--download", action="store_true", help="Download a range of comics into the DB")
    parser.add_argument("--start", type=int, default=1, help="Start comic number (inclusive)")
    parser.add_argument("--end", type=int, help="End comic number (inclusive). If omitted, uses latest comic")
    parser.add_argument("--no-resume", dest="resume", action="store_false", help="Do not skip comics already in DB")
    parser.add_argument("--delay", type=float, default=0.5, help="Delay in seconds between requests")
    args = parser.parse_args()

    print("Setup fertig!")
    if args.download:
        # Download-Loop mit den übergebenen Optionen starten
        download_comics(start=args.start, end=args.end, resume=args.resume, delay=args.delay)
    else:
        # Fallback: interaktiver Test
        test()