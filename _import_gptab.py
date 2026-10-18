import os
import re
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
LOCAL_ROOT_DIR = Path("/media/florent/Data/workspaces/WK_VS_Code/getMyPartition/download")

# Initialisation des clients
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
mongo_client = MongoClient(MONGO_URI)
db = mongo_client[DB_NAME]
collection = db[COLLECTION_NAME]

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
        
    return "Inconnu", filename_stem.strip()

def process_and_upload():
    if not LOCAL_ROOT_DIR.exists():
        print(f"Erreur : Le dossier {LOCAL_ROOT_DIR} n'existe pas.")
        return

    # Recherche récursive de tous le fichiers .gp*
    files = [f for f in LOCAL_ROOT_DIR.glob("**/*") if f.is_file() and f.suffix.lower() in ['.gp', '.gp3', '.gp4', '.gp5', '.gpx']]
    total = len(files)
    
    print(f"Trouvé {total} fichiers Guitar Pro à traiter.")

    for file_index, file_path in enumerate(files, 1):
        filename = file_path.name
        storage_path = filename  # Stocké à la racine du bucket

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

        # 2. Complément avec les métadonnées internes du fichier (pyguitarpro)
        try:
            song = guitarpro.parse(str(file_path))
            
            # Utilisation de getattr pour éviter tout attribut manquant selon les versions de guitarpro
            album = getattr(song, 'album', '')
            if album and album.strip():
                song_metadata["album"] = album.strip()

            copyright_txt = getattr(song, 'copyright', '')
            if copyright_txt and copyright_txt.strip():
                song_metadata["copyright"] = copyright_txt.strip()
                
            if not song_metadata["title"] and song.title and song.title.strip():
                song_metadata["title"] = song.title.strip()
            if (not song_metadata["artist"] or song_metadata["artist"] == "Inconnu") and song.artist and song.artist.strip():
                song_metadata["artist"] = song.artist.strip()

            tracks_list = []
            for track_index, track in enumerate(song.tracks):
                raw_name = track.name
                if isinstance(raw_name, bytes):
                    try:
                        track_name = raw_name.decode('utf-8')
                    except UnicodeDecodeError:
                        track_name = raw_name.decode('latin-1', errors='ignore')
                else:
                    track_name = str(raw_name)

                tracks_list.append({
                    "index": track_index,
                    "name": track_name.strip() if track_name else f"Piste {track_index + 1}"
                })

            song_metadata["tracks"] = tracks_list
                
        except Exception as e:
            print(f"  ❌ ERREUR DE PARSING BINAIRE : {e}")

        try:
            # 3. VÉRIFICATION DE DOUBLON (par Artiste et Titre) AVANT IMPORT
            existing_doc = collection.find_one({
                "metadata.artist": {"$regex": f"^{re.escape(song_metadata['artist'])}$", "$options": "i"},
                "metadata.title": {"$regex": f"^{re.escape(song_metadata['title'])}$", "$options": "i"}
            })

            if existing_doc:
                print(f"[{file_index}/{total}] Ignoré (Déjà en base) : {song_metadata['artist']} - {song_metadata['title']}")
                continue

            # 4. Lecture du fichier binaire pour l'upload
            with open(file_path, "rb") as f:
                file_bytes = f.read()

            # 5. Dépôt à la racine du bucket Supabase privé
            supabase.storage.from_(BUCKET_NAME).upload(
                path=storage_path,
                file=file_bytes,
                file_options={"upsert": "true"}
            )

            # 6. Enregistrement dans MongoDB Atlas
            doc = {
                "filename": filename,
                "storage_path": storage_path,
                "metadata": song_metadata,
                "local_source_path": str(file_path.relative_to(LOCAL_ROOT_DIR))
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