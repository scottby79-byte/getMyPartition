#!/usr/bin/env python3
"""
Script d'extraction de partitions Guitar Pro (.gp / .gp5) via Songsterr.
Utilisable en ligne de commande ou comme module pour le serveur web.
"""

import sys
import json
import re
import urllib.request
import urllib.parse
from pathlib import Path

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0"
SONGSTERR_REFERER = "https://www.songsterr.com/"


def clean_filename(s: str) -> str:
    """Nettoie une chaîne pour en faire un nom de fichier valide."""
    return re.sub(r'[\\/*?:"<>|]', "", s).strip().replace(" ", "_")


def search_songs(query: str) -> list:
    """Recherche des morceaux sur Songsterr par mot-clé (artiste et/ou titre)."""
    encoded_query = urllib.parse.quote(query.strip())
    url = f"https://www.songsterr.com/api/songs?pattern={encoded_query}"
    
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Referer": SONGSTERR_REFERER}
    )
    
    with urllib.request.urlopen(req, timeout=10) as response:
        data = json.loads(response.read().decode("utf-8"))
        return data


def get_song_gp_source(song_id: int) -> dict:
    """
    Récupère l'URL source directe du fichier Guitar Pro (.gp5 ou .gp)
    à partir du songId Songsterr.
    """
    # Étape 1 : Récupérer les métadonnées pour avoir le revisionId
    meta_url = f"https://www.songsterr.com/api/meta/{song_id}"
    req_meta = urllib.request.Request(
        meta_url,
        headers={"User-Agent": USER_AGENT, "Referer": SONGSTERR_REFERER}
    )
    with urllib.request.urlopen(req_meta, timeout=10) as response:
        meta_data = json.loads(response.read().decode("utf-8"))
    
    revision_id = meta_data.get("revisionId")
    if not revision_id:
        raise ValueError(f"Impossible de trouver le revisionId pour le morceau ID {song_id}")
    
    # Étape 2 : Récupérer les informations de la révision
    rev_url = f"https://www.songsterr.com/api/revision/{revision_id}"
    req_rev = urllib.request.Request(
        rev_url,
        headers={"User-Agent": USER_AGENT, "Referer": SONGSTERR_REFERER}
    )
    with urllib.request.urlopen(req_rev, timeout=10) as response:
        rev_data = json.loads(response.read().decode("utf-8"))
    
    source_url = rev_data.get("source")
    if not source_url:
        raise ValueError(f"Aucune source Guitar Pro disponible pour la révision {revision_id}")
    
    return {
        "song_id": song_id,
        "revision_id": revision_id,
        "artist": meta_data.get("artist"),
        "title": meta_data.get("title"),
        "source_url": source_url,
        "tracks": rev_data.get("tracks", []),
    }


def download_gp_file(source_url: str, output_path: Path) -> Path:
    """Télécharge le fichier Guitar Pro depuis le serveur Songsterr."""
    req = urllib.request.Request(
        source_url,
        headers={
            "User-Agent": USER_AGENT,
            "Referer": SONGSTERR_REFERER
        }
    )
    with urllib.request.urlopen(req, timeout=15) as response:
        content = response.read()
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(content)
    
    return output_path


def search_and_download(artist: str, title: str, output_dir: Path = Path(".")) -> dict:
    """Recherche un morceau par artiste et titre, puis télécharge le premier résultat."""
    query = f"{artist} {title}".strip()
    results = search_songs(query)
    
    if not results:
        raise RuntimeError(f"Aucun morceau trouvé pour la recherche : '{query}'")
    
    first = results[0]
    song_id = first["songId"]
    details = get_song_gp_source(song_id)
    
    ext = ".gp5" if ".gp5" in details["source_url"] else ".gp"
    filename = f"{clean_filename(details['artist'])}_{clean_filename(details['title'])}{ext}"
    target_path = output_dir / filename
    
    download_gp_file(details["source_url"], target_path)
    details["saved_path"] = str(target_path)
    return details


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python3 extract_partition.py <Artiste> <Titre> [dossier_destination]")
        print("Exemple: python3 extract_partition.py 'Izia' 'Let Me Alone'")
        sys.exit(1)
        
    art = sys.argv[1]
    tit = sys.argv[2]
    out = Path(sys.argv[3]) if len(sys.argv) > 3 else Path(".")
    
    print(f"🔍 Recherche de '{art} - {tit}'...")
    try:
        res = search_and_download(art, tit, out)
        print(f"✅ Partition téléchargée avec succès !")
        print(f"   Artiste : {res['artist']}")
        print(f"   Titre   : {res['title']}")
        print(f"   Source  : {res['source_url']}")
        print(f"   Fichier : {res['saved_path']}")
    except Exception as e:
        print(f"❌ Erreur : {e}")
        sys.exit(1)
