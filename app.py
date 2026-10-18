#!/usr/bin/env python3
"""
Application Web & API REST pour l'extraction de partitions Guitar Pro (.gp / .gp5 / .gp4 / .gp3 / .gpx).
Compatible WSGI (Gunicorn en production, Flask dev server en local).

Architecture multi-sources :
  Les sources de partitions sont des modules indépendants qui exposent tous la même interface :
    - search_songs(query: str) -> list[dict]
    - get_song_gp_source(song_id) -> dict
    - download_gp_file(source_url, output_path) -> Path
    - SOURCE_ID   : str  (identifiant technique unique)
    - SOURCE_LABEL: str  (libellé affiché dans l'interface)

  Pour ajouter une nouvelle source :
    1. Créer un module respectant l'interface ci-dessus.
    2. L'ajouter dans la liste SOURCES (dans l'ordre d'affichage souhaité).
"""

import os
import sys
import time
import threading
import io
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from flask import Flask, request, jsonify, send_file, send_from_directory
from pymongo import MongoClient
from supabase import create_client
from dotenv import load_dotenv

import songsterr
import myguitarpro

load_dotenv()
if not os.getenv("MONGO_URI") and Path("production.env").exists():
    load_dotenv("production.env")

# ---------------------------------------------------------------------------
# Répertoires
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
PARTITIONS_DIR = BASE_DIR / "download"
PARTITIONS_DIR.mkdir(exist_ok=True)

app = Flask(__name__, static_folder=str(BASE_DIR), static_url_path="")

# ---------------------------------------------------------------------------
# Initialisation des services cloud
# ---------------------------------------------------------------------------

# Initialisation sécurisée avec valeur par défaut si non renseigné
KEEP_ALIVE_CHECK = int(os.getenv("KEEP_ALIVE_CHECK", "600"))
SUPABASE_URL  = os.getenv("SUPABASE_URL")
SUPABASE_KEY  = os.getenv("SUPABASE_KEY")
BUCKET_NAME   = os.getenv("SUPABASE_BUCKET")
MONGO_URI     = os.getenv("MONGO_URI")
MONGO_DBNAME  = os.getenv("MONGO_DBNAME", "GetMyPartition")
MONGO_COLLECTION_GPTAB_NAME = os.getenv("MONGO_COLLECTION_GPTAB_NAME", "GuitarProTab")
MONGO_COLLECTION_SEARCH = os.getenv("MONGO_COLLECTION_SEARCH_NAME", "LastSearch")

try:
    supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL else None
    
    if MONGO_URI:
        mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        mongo_db = mongo_client[MONGO_DBNAME]
        mongo_collection = mongo_db[MONGO_COLLECTION_GPTAB_NAME]
        mongo_search_collection = mongo_db[MONGO_COLLECTION_SEARCH]
    else:
        mongo_client = None
        mongo_db = None
        mongo_collection = None
        mongo_search_collection = None
except Exception as e:
    print(f"❌ Erreur lors de l'initialisation des clients cloud : {e}")
    supabase_client         = None
    mongo_client            = None
    mongo_db                = None
    mongo_collection        = None
    mongo_search_collection = None

# Injection des dépendances dans la source mygppro
myguitarpro.init(
    mongo_collection=mongo_collection,
    supabase_client=supabase_client,
    bucket_name=BUCKET_NAME,
)

# ---------------------------------------------------------------------------
# Registre des sources — ordre = ordre d'affichage dans l'interface
# Pour ajouter une source, l'insérer ici à la position souhaitée.
# ---------------------------------------------------------------------------
SOURCES: list = [
    songsterr,  # 1. Songsterr (source externe)
    myguitarpro,    # 2. Bibliothèque personnelle (MongoDB + Supabase)
    # gprotab,  # 3. GProTab — à décommenter quand le module sera prêt
]


# ---------------------------------------------------------------------------
# Keep-alive : ping MongoDB & Supabase toutes les 10 minutes
# ---------------------------------------------------------------------------
def background_keep_alive():
    """
    Tâche de fond qui ping MongoDB et Supabase toutes les 10 minutes
    avec un mécanisme de timeout pour éviter tout blocage.
    """
    while True:
        time.sleep(KEEP_ALIVE_CHECK)
        print("🔄 [Keep-Alive] Ping interne vers MongoDB et Supabase...")

        if mongo_db is not None:
            try:
                mongo_db.command("ping")
                print("   -> MongoDB Atlas : OK")
            except Exception as e:
                print(f"   -> MongoDB Atlas Erreur (Timeout/Connexion) : {e}")

        if supabase_client is not None and BUCKET_NAME:
            try:
                res = supabase_client.storage.from_(BUCKET_NAME).list(options={"limit": 1})
                print(f"   -> Supabase Storage : OK (éléments: {len(res) if isinstance(res, list) else 'OK'})")
            except Exception as e:
                print(f"   -> Supabase Storage Erreur (Exception levée) : {e}")


keep_alive_thread = threading.Thread(target=background_keep_alive, daemon=True)
keep_alive_thread.start()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    """Sert l'interface web."""
    return send_from_directory(str(BASE_DIR), "index.html")


def record_search(artist: str, title: str, search_term: str):
    """
    Enregistre la recherche effectuée dans la collection LastSearch de MongoDB.
    Met à jour la date et incrémente le compteur sans créer de doublon.
    """
    if mongo_search_collection is None:
        return
    try:
        clean_artist = (artist or "").strip()
        clean_title  = (title or "").strip()
        clean_term   = (search_term or "").strip()

        if not clean_term:
            return

        # Libellé lisible pour les tags de suggestion
        display_label = f"{clean_artist} - {clean_title}" if clean_artist and clean_title else (clean_artist or clean_title or clean_term)

        # Clé unique pour dédupliquer proprement
        if clean_artist and clean_title:
            search_key = f"{clean_artist.lower()}__{clean_title.lower()}"
        else:
            search_key = clean_term.lower()

        mongo_search_collection.update_one(
            {"search_key": search_key},
            {
                "$set": {
                    "search_key": search_key,
                    "artist": clean_artist,
                    "title": clean_title,
                    "query": clean_term,
                    "display": display_label,
                    "updated_at": datetime.now(timezone.utc),
                },
                "$inc": {"count": 1}
            },
            upsert=True
        )
    except Exception as e:
        print(f"⚠️ [Mongo LastSearch] Erreur d'enregistrement : {e}")


@app.route("/api/recent-searches", methods=["GET"])
def api_recent_searches():
    """
    Retourne les 20 dernières recherches enregistrées dans MongoDB,
    triées de la plus récente à la plus ancienne.
    """
    if mongo_search_collection is None:
        return jsonify({"success": True, "searches": []})

    try:
        cursor = mongo_search_collection.find(
            {},
            {"_id": 0, "artist": 1, "title": 1, "query": 1, "display": 1}
        ).sort("updated_at", -1).limit(20)

        searches = list(cursor)
        return jsonify({"success": True, "searches": searches})
    except Exception as e:
        return jsonify({"success": False, "error": f"Erreur lors de la récupération des recherches : {e}"}), 500


@app.route("/api/search", methods=["GET"])
def api_search():
    """
    Recherche des morceaux sur toutes les sources actives en parallèle.
    Les résultats sont regroupés par source, dans l'ordre du registre SOURCES.
    Chaque groupe porte un label et un identifiant de source.
    """
    query  = request.args.get("q", "").strip()
    artist = request.args.get("artist", "").strip()
    title  = request.args.get("title", "").strip()

    search_term = query or f"{artist} {title}".strip()
    if not search_term:
        return jsonify({"success": False, "error": "Veuillez fournir un nom d'artiste ou un titre"}), 400

    # Enregistrement asynchrone de la recherche pour ne pas impacter la réactivité
    threading.Thread(target=record_search, args=(artist, title, search_term), daemon=True).start()

    # Interrogation parallèle de toutes les sources
    results_by_source: dict[str, list] = {}
    errors_by_source:  dict[str, str]  = {}

    def _search_source(source):
        try:
            hits = source.search_songs(search_term)
            # Garantit que chaque résultat porte l'identifiant de sa source
            for hit in hits:
                hit.setdefault("source", source.SOURCE_ID)
            return source.SOURCE_ID, hits, None
        except Exception as e:
            return source.SOURCE_ID, [], str(e)

    with ThreadPoolExecutor(max_workers=len(SOURCES)) as pool:
        futures = {pool.submit(_search_source, src): src for src in SOURCES}
        for future in as_completed(futures):
            source_id, hits, error = future.result()
            results_by_source[source_id] = hits
            if error:
                errors_by_source[source_id] = error

    # Reconstruction dans l'ordre du registre
    ordered_groups = [
        {
            "source_id":    src.SOURCE_ID,
            "source_label": src.SOURCE_LABEL,
            "results":      results_by_source.get(src.SOURCE_ID, []),
            "error":        errors_by_source.get(src.SOURCE_ID),
        }
        for src in SOURCES
    ]

    return jsonify({
        "success": True,
        "query":   search_term,
        "groups":  ordered_groups,
    })


@app.route("/api/song", methods=["GET"])
def api_song():
    """Récupère les détails d'un morceau depuis la source indiquée."""
    song_id   = request.args.get("id", "").strip()
    source_id = request.args.get("source", songsterr.SOURCE_ID).strip()

    if not song_id:
        return jsonify({"success": False, "error": "ID de morceau manquant"}), 400

    source = _get_source(source_id)
    if source is None:
        return jsonify({"success": False, "error": f"Source inconnue : {source_id!r}"}), 400

    # Songsterr attend un entier
    parsed_id = _parse_id(song_id, source_id)

    try:
        details = source.get_song_gp_source(parsed_id)
        return jsonify({"success": True, "details": details})
    except Exception as e:
        return jsonify({"success": False, "error": f"Erreur de récupération : {str(e)}"}), 500


@app.route("/api/check", methods=["GET"])
def api_check():
    """Vérifie si une partition Guitar Pro est disponible pour un morceau."""
    song_id   = request.args.get("id", "").strip()
    source_id = request.args.get("source", songsterr.SOURCE_ID).strip()

    if not song_id:
        return jsonify({"success": False, "error": "ID de morceau manquant"}), 400

    source    = _get_source(source_id)
    parsed_id = _parse_id(song_id, source_id)

    try:
        details = source.get_song_gp_source(parsed_id)
        return jsonify({
            "success":    True,
            "available":  True,
            "song_id":    song_id,
            "source_url": details.get("source_url"),
        })
    except Exception as e:
        return jsonify({
            "success":   True,
            "available": False,
            "song_id":   song_id,
            "error":     str(e),
        })


@app.route("/api/download", methods=["GET", "POST"])
def api_download():
    """
    Télécharge le fichier GP depuis la source indiquée,
    le sauvegarde dans PARTITIONS_DIR et le renvoie au navigateur.
    """
    if request.method == "POST":
        data      = request.get_json(silent=True) or {}
        song_id   = str(data.get("id",     "")).strip()
        source_id = str(data.get("source", songsterr.SOURCE_ID)).strip()
    else:
        song_id   = request.args.get("id",     "").strip()
        source_id = request.args.get("source", songsterr.SOURCE_ID).strip()

    if not song_id:
        return jsonify({"success": False, "error": "ID de morceau manquant"}), 400

    source    = _get_source(source_id)
    if source is None:
        return jsonify({"success": False, "error": f"Source inconnue : {source_id!r}"}), 400

    parsed_id = _parse_id(song_id, source_id)

    try:
        details   = source.get_song_gp_source(parsed_id)
        source_url = details["source_url"]

        # Détection de l'extension
        url_path = urllib.parse.urlparse(source_url).path
        ext      = Path(url_path).suffix.lower()
        if not ext:
            for candidate in [".gp5", ".gp4", ".gp3", ".gpx", ".gp"]:
                if candidate in source_url.lower():
                    ext = candidate
                    break
            else:
                # Fallback sur le storage_path MongoDB si disponible
                ext = Path(song_id).suffix.lower() or ".gp"

        filename    = f"{source.clean_filename(details['artist'])}_{source.clean_filename(details['title'])}{ext}"
        target_path = PARTITIONS_DIR / filename

        source.download_gp_file(source_url, target_path)

        if request.args.get("direct") == "1":
            return send_file(
                str(target_path),
                as_attachment=True,
                download_name=filename,
                mimetype="application/octet-stream",
            )

        return jsonify({
            "success":  True,
            "filename": filename,
            "path":     str(target_path),
            "details":  details,
        })
    except Exception as e:
        return jsonify({"success": False, "error": f"Erreur de téléchargement : {str(e)}"}), 500


@app.route("/api/local-files", methods=["GET"])
def api_local_files():
    """Liste les fichiers de partitions présents dans le dossier de téléchargement."""
    try:
        gp_extensions = {".gp", ".gp5", ".gp4", ".gp3", ".gpx", ".mid", ".midi"}
        files = [
            {
                "name":     f.name,
                "size":     f.stat().st_size,
                "modified": f.stat().st_mtime,
            }
            for f in PARTITIONS_DIR.glob("*.*")
            if f.suffix.lower() in gp_extensions
        ]
        files.sort(key=lambda x: x["modified"], reverse=True)
        return jsonify({"success": True, "files": files})
    except Exception as e:
        return jsonify({"success": False, "error": f"Erreur lors du scan : {str(e)}"}), 500


@app.route("/api/local-download", methods=["GET"])
def api_local_download():
    """Télécharge un fichier déjà présent dans le dossier de téléchargement."""
    filename  = request.args.get("file", "").strip()
    if not filename:
        return jsonify({"success": False, "error": "Nom de fichier manquant"}), 400

    safe_name = os.path.basename(filename)
    target    = PARTITIONS_DIR / safe_name
    if not target.exists() or not target.is_file():
        return jsonify({"success": False, "error": "Fichier introuvable"}), 404

    return send_file(
        str(target),
        as_attachment=True,
        download_name=safe_name,
        mimetype="application/octet-stream",
    )


@app.route("/api/tab-file", methods=["GET"])
def api_tab_file():
    """
    Sert le contenu binaire d'une partition Guitar Pro (pour le lecteur alphaTab),
    évitant tout problème de restriction CORS ou d'accès à un bucket privé Supabase.
    """
    source_id = request.args.get("source", "").strip()

    # Source locale (fichier dans le dossier download/)
    if source_id == "local":
        filename = request.args.get("file", "").strip()
        if not filename:
            return jsonify({"success": False, "error": "Nom de fichier manquant"}), 400
        safe_name = os.path.basename(filename)
        target = PARTITIONS_DIR / safe_name
        if not target.exists() or not target.is_file():
            return jsonify({"success": False, "error": "Fichier local introuvable"}), 404
        return send_file(
            str(target),
            mimetype="application/octet-stream",
            as_attachment=False,
            download_name=safe_name,
        )

    song_id = request.args.get("id", "").strip()
    if not song_id:
        return jsonify({"success": False, "error": "ID de partition manquant"}), 400

    source = _get_source(source_id)
    if source is None:
        return jsonify({"success": False, "error": f"Source inconnue : {source_id!r}"}), 400

    parsed_id = _parse_id(song_id, source_id)

    try:
        if source_id == myguitarpro.SOURCE_ID:
            content, filename = myguitarpro.get_file_bytes(parsed_id)
        else:
            # Source externe (ex: Songsterr)
            details = source.get_song_gp_source(parsed_id)
            source_url = details["source_url"]

            url_path = urllib.parse.urlparse(source_url).path
            ext = Path(url_path).suffix.lower()
            if not ext:
                for candidate in [".gp5", ".gp4", ".gp3", ".gpx", ".gp"]:
                    if candidate in source_url.lower():
                        ext = candidate
                        break
                else:
                    ext = ".gp"

            filename = f"{source.clean_filename(details.get('artist', ''))}_{source.clean_filename(details.get('title', ''))}{ext}"
            req = urllib.request.Request(
                source_url,
                headers={"User-Agent": getattr(source, "USER_AGENT", "GetMyPartition/1.0")}
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                content = resp.read()

        return send_file(
            io.BytesIO(content),
            mimetype="application/octet-stream",
            as_attachment=False,
            download_name=filename,
        )
    except Exception as e:
        return jsonify({"success": False, "error": f"Impossible de charger la partition : {str(e)}"}), 500


# ---------------------------------------------------------------------------
# Helpers internes
# ---------------------------------------------------------------------------

def _get_source(source_id: str):
    """Retourne le module source correspondant à l'identifiant, ou None."""
    for src in SOURCES:
        if src.SOURCE_ID == source_id:
            return src
    return None


def _parse_id(song_id: str, source_id: str):
    """
    Songsterr attend un entier ; les autres sources travaillent avec des chaînes.
    """
    if source_id == songsterr.SOURCE_ID and song_id.isdigit():
        return int(song_id)
    return song_id


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("PORT", 8080))
    print(f"🎸 Serveur Flask démarré sur : http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
