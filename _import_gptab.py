import os
import re
import unicodedata
import hashlib
from pathlib import Path
import guitarpro
from supabase import create_client
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()
if not os.getenv("MONGO_URI") and Path("production.env").exists():
    load_dotenv("production.env")

# --- CONFIGURATION ---
SUPABASE_URL  = os.getenv("SUPABASE_URL")
SUPABASE_KEY  = os.getenv("SUPABASE_KEY")
BUCKET_NAME   = os.getenv("SUPABASE_BUCKET")
MONGO_URI     = os.getenv("MONGO_URI")
DB_NAME       = os.getenv("MONGO_DBNAME", "GetMyPartition")
COLLECTION_NAME = os.getenv("MONGO_COLLECTION_GPTAB_NAME", "GuitarProTab")

# Chemin vers le dossier racine contenant vos sous-dossiers et fichiers .gp*
LOCAL_ROOT_DIR = Path("/media/florent/Data/Florent_data/Mes Medias/Guitar_Pro/guitare-et-couleurs.com")

# Initialisation des clients
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
mongo_client = MongoClient(MONGO_URI)
db = mongo_client[DB_NAME]
collection = db[COLLECTION_NAME]

def sanitize_storage_path(filename: str) -> str:
    """
    Convertit un nom de fichier en clé de stockage Supabase/S3 compatible ASCII.
    Conserve l'extension et neutralise les accents et caractères interdits dans les URL.
    """
    clean_name = filename.replace('/', '_').replace('\\', '_')
    stem = Path(clean_name).stem
    suffix = Path(clean_name).suffix.lower()

    # Normalisation NFKD : décompose les accents (ex: é -> e + accent combiné)
    nfkd = unicodedata.normalize('NFKD', stem)
    ascii_stem = nfkd.encode('ascii', 'ignore').decode('ascii')

    # Remplacement des caractères interdits ou problématiques dans les URL S3
    ascii_stem = re.sub(r'[\r\n\t\x00-\x1f#?%\\/*:"<>|]', '_', ascii_stem).strip()
    ascii_stem = re.sub(r'_+', '_', ascii_stem)

    if not ascii_stem:
        h = hashlib.md5(filename.encode('utf-8', errors='ignore')).hexdigest()[:12]
        ascii_stem = f"track_{h}"

    return f"{ascii_stem}{suffix}"

def parse_filename(filename_stem):
    """
    Extrait l'artiste et le titre d'un nom du type: [Artiste] - [Titre] ou Artiste - Titre
    """
    match = re.match(r"^\[(.*?)\]\s*-\s*(.*)$", filename_stem)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    
    if " - " in filename_stem:
        parts = filename_stem.split(" - ", 1)
        return parts[0].strip(), parts[1].strip()

    if "_-_" in filename_stem:
        parts = filename_stem.split("_-_", 1)
        return parts[0].replace('_', ' ').strip(), parts[1].replace('_', ' ').strip()
        
    return "Inconnu", filename_stem.strip()

def safe_parse_guitarpro(file_path: Path):
    """
    Tente de parser la tablature avec plusieurs encodages (cp1252, utf-8, latin-1)
    pour éviter les plantages sur les caractères accentués ou non-ASCII.
    """
    for enc in ('cp1252', 'utf-8', 'latin-1'):
        try:
            return guitarpro.parse(str(file_path), encoding=enc)
        except Exception:
            continue
    return None

def process_and_upload():
    if not LOCAL_ROOT_DIR.exists():
        print(f"Erreur : Le dossier {LOCAL_ROOT_DIR} n'existe pas.")
        return

    # Recherche récursive de tous les fichiers .gp*
    files = [f for f in LOCAL_ROOT_DIR.glob("**/*") if f.is_file() and f.suffix.lower() in ['.gp', '.gp3', '.gp4', '.gp5', '.gpx']]
    total = len(files)
    
    print(f"Trouvé {total} fichiers Guitar Pro à traiter.")

    for file_index, file_path in enumerate(files, 1):
        filename = file_path.name
        rel_path = str(file_path.relative_to(LOCAL_ROOT_DIR))

        # 1. Extraction prioritaire depuis le nom de fichier
        file_stem = file_path.stem
        extracted_artist, extracted_title = parse_filename(file_stem)

        song_metadata = {
            "title": extracted_title,
            "artist": extracted_artist,
            "album": "",
            "author": "",
            "copyright": "",
            "tab": "",
            "tracks": []
        }

        # 2. Complément avec les métadonnées internes du fichier (pyguitarpro multi-encodage)
        try:
            song = safe_parse_guitarpro(file_path)
            if song:
                album = getattr(song, 'album', '')
                if album and str(album).strip():
                    song_metadata["album"] = str(album).strip()

                copyright_txt = getattr(song, 'copyright', '')
                if copyright_txt and str(copyright_txt).strip():
                    song_metadata["copyright"] = str(copyright_txt).strip()
                    
                if not song_metadata["title"] and getattr(song, 'title', None) and str(song.title).strip():
                    song_metadata["title"] = str(song.title).strip()
                if (not song_metadata["artist"] or song_metadata["artist"] == "Inconnu") and getattr(song, 'artist', None) and str(song.artist).strip():
                    song_metadata["artist"] = str(song.artist).strip()

                tracks_list = []
                for track_index, track in enumerate(getattr(song, 'tracks', [])):
                    raw_name = getattr(track, 'name', '')
                    if isinstance(raw_name, bytes):
                        for enc in ('utf-8', 'cp1252', 'latin-1'):
                            try:
                                track_name = raw_name.decode(enc)
                                break
                            except UnicodeDecodeError:
                                continue
                        else:
                            track_name = raw_name.decode('latin-1', errors='replace')
                    else:
                        track_name = str(raw_name)

                    tracks_list.append({
                        "index": track_index,
                        "name": track_name.strip() if track_name else f"Piste {track_index + 1}"
                    })

                song_metadata["tracks"] = tracks_list
            else:
                print(f"  ⚠️ Avertissement : Impossible d'extraire les métadonnées binaires pour {filename}")
                
        except Exception as e:
            print(f"  ❌ ERREUR DE PARSING BINAIRE : {e}")

        # 3. Génération d'un storage_path compatible ASCII pour Supabase / S3
        storage_path = sanitize_storage_path(filename)

        # Résolution des collisions de nom si deux fichiers différents ont le même nom ASCII
        base_storage_path = storage_path
        counter = 1
        while collection.find_one({"storage_path": storage_path, "local_source_path": {"$ne": rel_path}}):
            counter += 1
            s_stem = Path(base_storage_path).stem
            s_suffix = Path(base_storage_path).suffix
            storage_path = f"{s_stem}_{counter}{s_suffix}"

        try:
            # 4. VÉRIFICATION DE DOUBLON AVANT IMPORT
            # Si le fichier exact existe déjà en base avec le même chemin relatif ou même storage_path
            existing_doc = collection.find_one({
                "$or": [
                    {"local_source_path": rel_path},
                    {"storage_path": storage_path}
                ]
            })

            # Si pas de correspondance exacte, vérification par Artiste et Titre (si connus)
            if not existing_doc and song_metadata['artist'] and song_metadata['artist'] != "Inconnu" and song_metadata['title']:
                existing_doc = collection.find_one({
                    "metadata.artist": {"$regex": f"^{re.escape(song_metadata['artist'])}$", "$options": "i"},
                    "metadata.title": {"$regex": f"^{re.escape(song_metadata['title'])}$", "$options": "i"}
                })

            if existing_doc:
                print(f"[{file_index}/{total}] Ignoré (Déjà en base) : {song_metadata['artist']} - {song_metadata['title']}")
                continue

            # 5. Lecture du fichier binaire pour l'upload
            with open(file_path, "rb") as f:
                file_bytes = f.read()

            # 6. Dépôt à la racine du bucket Supabase privé (clé ASCII sécurisée)
            supabase.storage.from_(BUCKET_NAME).upload(
                path=storage_path,
                file=file_bytes,
                file_options={"upsert": "true"}
            )

            # 7. Enregistrement dans MongoDB Atlas avec nom original (accents, apostrophes)
            doc = {
                "filename": filename,
                "storage_path": storage_path,
                "metadata": song_metadata,
                "local_source_path": rel_path
            }

            collection.update_one(
                {"storage_path": storage_path},
                {"$set": doc},
                upsert=True
            )

            print(f"[{file_index}/{total}] Succès : Artiste -> {song_metadata['artist']} | Titre -> {song_metadata['title']} ({len(song_metadata['tracks'])} pistes)")

        except Exception as e:
            print(f"[{file_index}/{total}] Erreur critique sur {filename}: {e}")

    print("Importation et migration terminées avec succès !")

if __name__ == "__main__":
    process_and_upload()