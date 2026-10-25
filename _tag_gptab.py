import os
import re
import urllib.parse
import urllib.request
from pathlib import Path
import guitarpro
import tempfile
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

# Initialisation des clients
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
mongo_client = MongoClient(MONGO_URI)
db = mongo_client[DB_NAME]
collection = db[COLLECTION_NAME]

def safe_parse_guitarpro(file_path: str):
    """Tente de parser la tablature avec plusieurs encodages pour gérer les accents."""
    for enc in ('cp1252', 'utf-8', 'latin-1'):
        try:
            return guitarpro.parse(str(file_path), encoding=enc)
        except Exception:
            continue
    return None

def download_file_bytes(storage_path: str) -> bytes:
    """Télécharge les octets d'un fichier avec gestion des chemins encodés et fallback URL signée."""
    # 1. Tentative directe
    try:
        return supabase.storage.from_(BUCKET_NAME).download(storage_path)
    except Exception:
        pass

    # 2. Tentative avec unquote
    unquoted = urllib.parse.unquote(storage_path)
    if unquoted != storage_path:
        try:
            return supabase.storage.from_(BUCKET_NAME).download(unquoted)
        except Exception:
            pass

    # 3. Fallback via URL signée
    signed = supabase.storage.from_(BUCKET_NAME).create_signed_url(storage_path, 120)
    signed_url = signed.get("signedURL") or signed.get("signedUrl")
    if signed_url:
        req = urllib.request.Request(signed_url, headers={"User-Agent": "GetMyPartition/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read()

    raise RuntimeError(f"Fichier introuvable sur Supabase pour {storage_path}")

def migrate_tracks():
    documents = collection.find({})
    count = 0
    
    for doc in documents:
        doc_id = doc["_id"]
        storage_path = doc.get("storage_path")
        
        if not storage_path:
            print(f"Skipping doc {doc_id}: pas de storage_path")
            continue
            
        print(f"Traitement de : {storage_path}...")
        
        try:
            # 1. Télécharger le fichier binaire depuis le bucket privé Supabase
            res = download_file_bytes(storage_path)
            
            if not res:
                print(f"  -> Fichier vide sur Supabase pour {storage_path}")
                continue
                
            # 2. Utiliser un fichier temporaire pour que guitarpro puisse le parser proprement
            ext = Path(storage_path).suffix or ".gp"
            with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
                tmp.write(res)
                tmp_path = tmp.name
                
            try:
                # 3. Parser la tablature avec la lib python guitarpro (multi-encodage)
                song = safe_parse_guitarpro(tmp_path)
                if not song:
                    print(f"  -> Impossible de parser la partition {storage_path}")
                    continue
                
                # Extraire les pistes sous forme de liste de dictionnaires
                tracks_list = []
                for index, track in enumerate(getattr(song, 'tracks', [])):
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
                        "index": index,
                        "name": track_name.strip() if track_name else f"Piste {index + 1}"
                    })
                
                # 4. Mettre à jour le document MongoDB avec le nouveau tableau tracks
                collection.update_one(
                    {"_id": doc_id},
                    {"$set": {"metadata.tracks": tracks_list}}
                )
                
                count += 1
                print(f"  -> Succès : {len(tracks_list)} piste(s) ajoutée(s).")
                
            finally:
                # Nettoyage du fichier temporaire
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
                    
        except Exception as e:
            print(f"  -> Erreur sur {storage_path} : {e}")
            
    print(f"\nMigration terminée ! {count} documents mis à jour avec succès.")

if __name__ == "__main__":
    migrate_tracks()