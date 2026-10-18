import os
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, OperationFailure
from dotenv import load_dotenv

# Charge les variables du fichier .env si présent
load_dotenv()

MONGO_URI     = os.getenv("MONGO_URI")
MONGO_DBNAME  = os.getenv("MONGO_DBNAME", "GetMyPartition")
MONGO_COLLECTION = os.getenv("MONGO_COLLECTION_GPTAB_NAME", "GuitarProTab")

print(f"🔍 URI MongoDB détectée : {'Définie (longueur: ' + str(len(MONGO_URI)) + ')' if MONGO_URI else 'NON DÉFINIE !'}")

if not MONGO_URI:
    print("❌ Erreur : La variable MONGO_URI est vide ou introuvable.")
    exit(1)

try:
    print("⏳ Tentative de connexion à MongoDB Atlas (timeout 5s)...")
    # serverSelectionTimeoutMS=5000 force l'échec après 5 secondes si le serveur ne répond pas
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    db = client[MONGO_DBNAME]
    coll = db[MONGO_COLLECTION]
    
    # Force un appel réseau réel pour valider l'authentification et la connexion
    print(coll)
    db.command('ping')
        
    print("✅ Connexion à MongoDB Atlas réussie avec succès !")
    
    # Affiche la liste des bases de données accessibles pour confirmer les droits
    dbs = client.list_database_names()
    print(f"📂 Bases de données disponibles sur ce cluster : {dbs}")

except ConnectionFailure as e:
    print(f"❌ Échec de la connexion réseau (Problème DNS, IP non autorisée ou réseau bloqué) : {e}")
except OperationFailure as e:
    print(f"❌ Échec de l'authentification (Identifiants invalides / utilisateur ou mot de passe incorrect) : {e}")
except Exception as e:
    print(f"❌ Erreur inattendue : {e}")