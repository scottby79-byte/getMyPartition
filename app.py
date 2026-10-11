#!/usr/bin/env python3
"""
Application Web & API REST pour l'extraction de partitions Guitar Pro (.gp / .gp5).
Compatible WSGI (Gunicorn en production, Flask dev server en local).
"""

import os
import sys
from pathlib import Path
from flask import Flask, request, jsonify, send_file, send_from_directory

from extract_partition import (
    search_songs,
    get_song_gp_source,
    download_gp_file,
    clean_filename
)

BASE_DIR = Path(__file__).resolve().parent
PARTITIONS_DIR = BASE_DIR

app = Flask(__name__, static_folder=str(BASE_DIR), static_url_path="")


@app.route("/")
def index():
    """Sert l'interface web."""
    return send_from_directory(str(BASE_DIR), "index.html")


@app.route("/api/search", methods=["GET"])
def api_search():
    """Recherche des morceaux via Songsterr API."""
    query = request.args.get("q", "").strip()
    artist = request.args.get("artist", "").strip()
    title = request.args.get("title", "").strip()

    search_term = query or f"{artist} {title}".strip()
    if not search_term:
        return jsonify({"success": False, "error": "Veuillez fournir un nom d'artiste ou un titre"}), 400

    try:
        results = search_songs(search_term)
        return jsonify({"success": True, "results": results, "query": search_term})
    except Exception as e:
        return jsonify({"success": False, "error": f"Erreur de recherche : {str(e)}"}), 500


@app.route("/api/song", methods=["GET"])
def api_song():
    """Récupère les détails et pistes d'un morceau."""
    song_id = request.args.get("id", "").strip()
    if not song_id or not song_id.isdigit():
        return jsonify({"success": False, "error": "ID de morceau invalide"}), 400

    try:
        details = get_song_gp_source(int(song_id))
        return jsonify({"success": True, "details": details})
    except Exception as e:
        return jsonify({"success": False, "error": f"Erreur de récupération : {str(e)}"}), 500


@app.route("/api/download", methods=["GET", "POST"])
def api_download():
    """Télécharge le fichier GP5 et le sauvegarde localement."""
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        song_id = str(data.get("id", "")).strip()
    else:
        song_id = request.args.get("id", "").strip()

    if not song_id or not song_id.isdigit():
        return jsonify({"success": False, "error": "ID de morceau invalide"}), 400

    try:
        details = get_song_gp_source(int(song_id))
        ext = ".gp5" if ".gp5" in details["source_url"] else ".gp"
        filename = f"{clean_filename(details['artist'])}_{clean_filename(details['title'])}{ext}"
        target_path = PARTITIONS_DIR / filename

        download_gp_file(details["source_url"], target_path)

        # Si direct=1, on envoie directement le flux de téléchargement au navigateur
        if request.args.get("direct") == "1":
            return send_file(
                str(target_path),
                as_attachment=True,
                download_name=filename,
                mimetype="application/octet-stream"
            )

        return jsonify({
            "success": True,
            "filename": filename,
            "path": str(target_path),
            "details": details
        })
    except Exception as e:
        return jsonify({"success": False, "error": f"Erreur de téléchargement : {str(e)}"}), 500


@app.route("/api/local-files", methods=["GET"])
def api_local_files():
    """Liste les fichiers de partitions présents sur le serveur."""
    try:
        files = []
        for f in PARTITIONS_DIR.glob("*.*"):
            if f.suffix.lower() in [".gp", ".gp5", ".gpx", ".mid", ".midi"]:
                files.append({
                    "name": f.name,
                    "size": f.stat().st_size,
                    "modified": f.stat().st_mtime
                })
        files.sort(key=lambda x: x["modified"], reverse=True)
        return jsonify({"success": True, "files": files})
    except Exception as e:
        return jsonify({"success": False, "error": f"Erreur lors du scan : {str(e)}"}), 500


@app.route("/api/local-download", methods=["GET"])
def api_local_download():
    """Télécharge un fichier existant du serveur."""
    filename = request.args.get("file", "").strip()
    if not filename:
        return jsonify({"success": False, "error": "Nom de fichier manquant"}), 400

    safe_name = os.path.basename(filename)
    target = PARTITIONS_DIR / safe_name
    if not target.exists() or not target.is_file():
        return jsonify({"success": False, "error": "Fichier introuvable"}), 404

    return send_file(
        str(target),
        as_attachment=True,
        download_name=safe_name,
        mimetype="application/octet-stream"
    )


# Pour Gunicorn : l'objet WSGI est `app`
if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("PORT", 8080))
    print(f"🎸 Serveur Flask démarré sur : http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
