import os
import re
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
            res = supabase.storage.from_(BUCKET_NAME).download(storage_path)
            
            if not res:
                print(f"  -> Fichier introuvable sur Supabase pour {storage_path}")
                continue
                
            # 2. Utiliser un fichier temporaire pour que guitarpro puisse le parser proprement
            with tempfile.NamedTemporaryFile(delete=False, suffix=".gp") as tmp:
                tmp.write(res)
                tmp_path = tmp.name
                
            try:
                # 3. Parser la tablature avec la lib python guitarpro
                song = guitarpro.parse(tmp_path)
                
                # Extraire les pistes sous forme de liste de dictionnaires
                tracks_list = []
                for index, track in enumerate(song.tracks):
                    tracks_list.append({
                        "index": index,
                        "name": track.name
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