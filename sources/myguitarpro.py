#!/usr/bin/env python3
"""
Source : bibliothèque personnelle Guitar Pro.
Expose la même interface que songsterr.py pour être utilisée
de manière interchangeable par l'orchestrateur dans app.py.

Dépendances : pymongo, supabase (injectées depuis app.py via init())
"""

import re
import urllib.request
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


def make_fuzzy_regex(term: str) -> str:
    """
    Construit une expression régulière tolérante aux accents,
    aux différents types d'apostrophes (droite ' ou courbe ’),
    et aux séparateurs (espaces, tirets, underscores).
    """
    char_map = {
        "a": "[aàâäáãåAÀÂÄÁÃÅ]",
        "à": "[aàâäáãåAÀÂÄÁÃÅ]",
        "â": "[aàâäáãåAÀÂÄÁÃÅ]",
        "ä": "[aàâäáãåAÀÂÄÁÃÅ]",
        "e": "[eéèêëEÉÈÊË]",
        "é": "[eéèêëEÉÈÊË]",
        "è": "[eéèêëEÉÈÊË]",
        "ê": "[eéèêëEÉÈÊË]",
        "ë": "[eéèêëEÉÈÊË]",
        "i": "[iîïíIÎÏÍ]",
        "î": "[iîïíIÎÏÍ]",
        "ï": "[iîïíIÎÏÍ]",
        "o": "[oôöóõOÔÖÓÕ]",
        "ô": "[oôöóõOÔÖÓÕ]",
        "ö": "[oôöóõOÔÖÓÕ]",
        "u": "[uùûüúUÙÛÜÚ]",
        "ù": "[uùûüúUÙÛÜÚ]",
        "û": "[uùûüúUÙÛÜÚ]",
        "ü": "[uùûüúUÙÛÜÚ]",
        "c": "[cçCÇ]",
        "ç": "[cçCÇ]",
        "n": "[nñNÑ]",
        "'": "['’`]",
        "’": "['’`]",
        "`": "['’`]",
    }
    pattern_parts = []
    for ch in term:
        lower = ch.lower()
        if lower in char_map:
            pattern_parts.append(char_map[lower])
        elif ch in (" ", "_", "-"):
            pattern_parts.append(r"[\s_\-]+")
        else:
            pattern_parts.append(re.escape(ch))
    return "".join(pattern_parts)


def _find_song_doc(song_id: str):
    """
    Recherche un document par storage_path ou filename,
    en testant aussi la version URL-décodée pour supporter
    les caractères spéciaux, apostrophes et accents.
    """
    if _mongo_collection is None:
        return None

    # 1. Test direct storage_path
    doc = _mongo_collection.find_one({"storage_path": song_id})
    if doc:
        return doc

    # 2. Test direct filename
    doc = _mongo_collection.find_one({"filename": song_id})
    if doc:
        return doc

    # 3. Test version URL-décodée
    decoded = urllib.parse.unquote(song_id)
    if decoded != song_id:
        doc = _mongo_collection.find_one({"storage_path": decoded})
        if doc:
            return doc
        doc = _mongo_collection.find_one({"filename": decoded})
        if doc:
            return doc

    return None


# ---------------------------------------------------------------------------
# Interface commune (mirror de songsterr.py)
# ---------------------------------------------------------------------------

def search_songs(query: str) -> list[dict]:
    """
    Recherche des morceaux dans la collection MongoDB.
    Gère les accents, apostrophes et caractères spéciaux.
    """
    if not is_available():
        return []

    terms = query.strip().split()
    if not terms:
        return []

    # Chaque terme doit être présent dans artist, title OU filename (insensible à la casse et aux accents)
    conditions = []
    for term in terms:
        regex_pattern = make_fuzzy_regex(term)
        pattern = re.compile(regex_pattern, re.IGNORECASE)
        conditions.append({
            "$or": [
                {"metadata.artist": {"$regex": pattern}},
                {"metadata.title":  {"$regex": pattern}},
                {"filename":        {"$regex": pattern}},
                {"storage_path":    {"$regex": pattern}},
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
            "tracks": meta.get("tracks", []) if meta else [],
        })

    return results


def get_song_gp_source(song_id: str) -> dict:
    """
    Récupère l'URL signée Supabase du fichier Guitar Pro correspondant
    au storage_path ou filename (song_id).
    """
    if not is_available():
        raise RuntimeError("La source Ma bibliothèque n'est pas disponible (MongoDB/Supabase non configuré).")

    doc = _find_song_doc(song_id)
    if not doc:
        raise ValueError(f"Partition introuvable en base pour l'identifiant : {song_id!r}")

    storage_path = doc.get("storage_path") or song_id
    meta = doc.get("metadata", {})

    # Génération d'une URL signée temporaire (5 minutes)
    signed = _supabase_client.storage.from_(_bucket_name).create_signed_url(
        path=storage_path,
        expires_in=300
    )
    signed_url = signed.get("signedURL") or signed.get("signedUrl", "")
    if not signed_url:
        raise RuntimeError(f"Impossible de générer l'URL signée pour : {storage_path!r}")

    return {
        "song_id":    storage_path,
        "artist":     meta.get("artist", ""),
        "title":      meta.get("title",  ""),
        "source_url": signed_url,
        "source":     SOURCE_ID,
        "tracks":     meta.get("tracks", []),
    }


def download_gp_file(source_url: str, output_path: Path) -> Path:
    """
    Télécharge le fichier Guitar Pro depuis l'URL signée Supabase
    et le sauvegarde sur disque.
    """
    req = urllib.request.Request(source_url, headers={"User-Agent": "GetMyPartition/1.0"})
    with urllib.request.urlopen(req, timeout=30) as response:
        content = response.read()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(content)

    return output_path


def get_file_bytes(song_id: str) -> tuple[bytes, str]:
    """
    Télécharge et retourne les octets du fichier Guitar Pro depuis Supabase ainsi que son nom de fichier.
    """
    if not is_available():
        raise RuntimeError("La source Ma bibliothèque n'est pas disponible (MongoDB/Supabase non configuré).")

    doc = _find_song_doc(song_id)
    storage_path = doc.get("storage_path") if doc else song_id

    # Récupération du meilleur nom de fichier avec vrais accents et apostrophes
    if doc and doc.get("filename"):
        filename = doc["filename"]
    else:
        filename = Path(storage_path).name
        if doc:
            meta = doc.get("metadata", {})
            artist = clean_filename(meta.get("artist", ""))
            title = clean_filename(meta.get("title", ""))
            ext = Path(storage_path).suffix or ".gp"
            if artist and title:
                filename = f"{artist}_{title}{ext}"

    # Récupération directe depuis Supabase Storage
    try:
        content = _supabase_client.storage.from_(_bucket_name).download(storage_path)
        return content, filename
    except Exception:
        # Fallback 1 : essayer unquoted storage_path
        unquoted = urllib.parse.unquote(storage_path)
        if unquoted != storage_path:
            try:
                content = _supabase_client.storage.from_(_bucket_name).download(unquoted)
                return content, filename
            except Exception:
                pass

        # Fallback 2 : via URL signée si le download direct échoue
        signed_info = get_song_gp_source(storage_path)
        req = urllib.request.Request(signed_info["source_url"], headers={"User-Agent": "GetMyPartition/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            content = resp.read()
        return content, filename


def clean_filename(s: str) -> str:
    """
    Nettoie une chaîne pour en faire un nom de fichier valide,
    en préservant les accents, apostrophes et caractères valides.
    """
    if not s:
        return ""
    # Supprime uniquement les caractères interdits sur les systèmes de fichiers et contrôles HTTP
    cleaned = re.sub(r'[\r\n\t\x00-\x1f\\/*?:"<>|]', "", str(s)).strip()
    cleaned = re.sub(r'\s+', '_', cleaned)
    cleaned = re.sub(r'_+', '_', cleaned)
    return cleaned