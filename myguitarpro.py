#!/usr/bin/env python3
"""
Source : bibliothèque personnelle Guitar Pro.
Expose la même interface que songsterr.py pour être utilisée
de manière interchangeable par l'orchestrateur dans app.py.

Dépendances : pymongo, supabase (injectées depuis app.py via init())
"""

import re
import urllib.parse
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration – remplie à l'initialisation par app.py
# ---------------------------------------------------------------------------
_mongo_collection = None
_supabase_client  = None
_bucket_name      = None

SOURCE_ID   = "mygppro"          # identifiant unique de la source
SOURCE_LABEL = "Ma bibliothèque" # libellé affiché dans l'interface


def init(mongo_collection, supabase_client, bucket_name: str):
    """
    Initialise la source avec les clients déjà instanciés dans app.py.
    À appeler une seule fois au démarrage.
    """
    global _mongo_collection, _supabase_client, _bucket_name
    _mongo_collection = mongo_collection
    _supabase_client  = supabase_client
    _bucket_name      = bucket_name


def is_available() -> bool:
    """Retourne True si la source est correctement configurée."""
    return all([_mongo_collection is not None,
                _supabase_client  is not None,
                _bucket_name])


# ---------------------------------------------------------------------------
# Interface commune (mirror de songsterr.py)
# ---------------------------------------------------------------------------

def search_songs(query: str) -> list[dict]:
    """
    Recherche des morceaux dans la collection MongoDB.
    Retourne une liste de dicts normalisés identiques au format Songsterr.

    Format de sortie par élément :
      {
        "songId"  : str  (= storage_path, identifiant unique dans cette source)
        "artist"  : str,
        "title"   : str,
        "album"   : str,
        "source"  : SOURCE_ID,
        "tracks"  : []   (non disponible dans MongoDB pour l'instant)
      }
    """
    if not is_available():
        return []

    # Construction du filtre MongoDB : recherche sur artist ET title
    terms = query.strip().split()
    if not terms:
        return []

    # Chaque terme doit être présent dans artist OU title (insensible à la casse)
    conditions = []
    for term in terms:
        pattern = re.compile(re.escape(term), re.IGNORECASE)
        conditions.append({
            "$or": [
                {"metadata.artist": {"$regex": pattern}},
                {"metadata.title":  {"$regex": pattern}},
            ]
        })

    mongo_filter = {"$and": conditions} if len(conditions) > 1 else conditions[0]

    cursor = _mongo_collection.find(
        mongo_filter,
        {"storage_path": 1, "filename": 1, "metadata": 1}
    ).limit(50)

    results = []
    for doc in cursor:
        meta = doc.get("metadata", {})
        results.append({
            "songId": doc["storage_path"],   # sert d'identifiant unique
            "artist": meta.get("artist", ""),
            "title":  meta.get("title",  ""),
            "album":  meta.get("album",  ""),
            "source": SOURCE_ID,
            "tracks": meta.get("tracks", []) if meta else [],                     # pas d'info piste en base pour l'instant
        })

    return results


def get_song_gp_source(song_id: str) -> dict:
    """
    Récupère l'URL signée Supabase du fichier Guitar Pro correspondant
    au storage_path (song_id).

    Format de sortie :
      {
        "song_id"    : str,
        "artist"     : str,
        "title"      : str,
        "source_url" : str  (URL signée Supabase, valide 300 s),
        "source"     : SOURCE_ID,
        "tracks"     : []
      }
    """
    if not is_available():
        raise RuntimeError("La source Ma bibliothèque n'est pas disponible (MongoDB/Supabase non configuré).")

    # Décodage de l'URL/chemin reçu (ex: conversion de %20 en espaces)
    decoded_song_id = urllib.parse.unquote(song_id)

    doc = _mongo_collection.find_one({"storage_path": decoded_song_id})
    if not doc:
        raise ValueError(f"Partition introuvable en base pour le chemin : {decoded_song_id!r}")

    meta = doc.get("metadata", {})

    # Génération d'une URL signée temporaire (5 minutes) en utilisant la version décodée
    signed = _supabase_client.storage.from_(_bucket_name).create_signed_url(
        path=decoded_song_id,
        expires_in=300
    )
    signed_url = signed.get("signedURL") or signed.get("signedUrl", "")
    if not signed_url:
        raise RuntimeError(f"Impossible de générer l'URL signée pour : {decoded_song_id!r}")

    return {
        "song_id":    decoded_song_id,
        "artist":     meta.get("artist", ""),
        "title":      meta.get("title",  ""),
        "source_url": signed_url,
        "source":     SOURCE_ID,
        "tracks":     [],
    }


def download_gp_file(source_url: str, output_path: Path) -> Path:
    """
    Télécharge le fichier Guitar Pro depuis l'URL signée Supabase
    et le sauvegarde sur disque.
    Réutilise la même implémentation que songsterr.py.
    """
    import urllib.request

    req = urllib.request.Request(source_url, headers={"User-Agent": "GetMyPartition/1.0"})
    with urllib.request.urlopen(req, timeout=30) as response:
        content = response.read()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(content)

    return output_path


def clean_filename(s: str) -> str:
    """Nettoie une chaîne pour en faire un nom de fichier valide."""
    return re.sub(r'[\\/*?:"<>|]', "", s).strip().replace(" ", "_")