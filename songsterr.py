#!/usr/bin/env python3
"""
Script d'extraction de partitions Guitar Pro (.gp / .gp5 / .gp4 / .gp3 / .gpx) via Songsterr.
Utilisable en ligne de commande ou comme module pour le serveur web.
"""

import sys
import json
import re
import urllib.request
import urllib.parse
from pathlib import Path

from concurrent.futures import ThreadPoolExecutor

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0"
SONGSTERR_REFERER = "https://www.songsterr.com/"

# Identifiants de source — requis par l'interface commune (app.py)
SOURCE_ID    = "songsterr"
SOURCE_LABEL = "Songsterr"


def clean_filename(s: str) -> str:
    """Nettoie une chaîne pour en faire un nom de fichier valide, en préservant les accents et apostrophes."""
    if not s:
        return ""
    cleaned = re.sub(r'[\r\n\t\x00-\x1f\\/*?:"<>|]', "", str(s)).strip()
    cleaned = re.sub(r'\s+', '_', cleaned)
    cleaned = re.sub(r'_+', '_', cleaned)
    return cleaned


def verify_source_url(url: str) -> bool:
    """Vérifie via une requête HTTP HEAD que l'URL source est accessible."""
    if not url:
        return False
    try:
        req = urllib.request.Request(
            url,
            method="HEAD",
            headers={"User-Agent": USER_AGENT, "Referer": SONGSTERR_REFERER}
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except Exception:
        return False


def _fetch_revision(rev_id: int):
    """Récupère les informations JSON d'une révision spécifique."""
    rev_url = f"https://www.songsterr.com/api/revision/{rev_id}"
    req = urllib.request.Request(
        rev_url,
        headers={"User-Agent": USER_AGENT, "Referer": SONGSTERR_REFERER}
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return rev_id, json.loads(r.read().decode("utf-8"))
    except Exception:
        return rev_id, None


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
    Si la dernière révision ne possède pas de source (tablature modifiée sur l'éditeur web),
    parcourt automatiquement l'historique des révisions pour trouver la version
    Guitar Pro valide la plus récente.
    """
    # Étape 1 : Récupérer les métadonnées pour avoir le dernier revisionId
    meta_url = f"https://www.songsterr.com/api/meta/{song_id}"
    req_meta = urllib.request.Request(
        meta_url,
        headers={"User-Agent": USER_AGENT, "Referer": SONGSTERR_REFERER}
    )
    with urllib.request.urlopen(req_meta, timeout=10) as response:
        meta_data = json.loads(response.read().decode("utf-8"))
    
    latest_revision_id = meta_data.get("revisionId")
    if not latest_revision_id:
        raise ValueError(f"Impossible de trouver le revisionId pour le morceau ID {song_id}")
    
    # Étape 2 : Vérifier la dernière révision
    selected_rev_id, rev_data = _fetch_revision(latest_revision_id)
    source_url = rev_data.get("source") if rev_data else None

    if source_url and verify_source_url(source_url):
        found = True
    else:
        source_url = None
        found = False

    # Étape 3 : Si aucune source valide, exploration intelligente de l'historique des révisions
    if not found:
        hist_url = f"https://www.songsterr.com/api/meta/{song_id}/revisions"
        req_hist = urllib.request.Request(
            hist_url,
            headers={"User-Agent": USER_AGENT, "Referer": SONGSTERR_REFERER}
        )
        try:
            with urllib.request.urlopen(req_hist, timeout=10) as resp_hist:
                revisions = json.loads(resp_hist.read().decode("utf-8"))
        except Exception:
            revisions = []

        # Construction des révisions candidates ordonnées par pertinence :
        candidate_ids = []
        
        # 1. Imports explicites GP ('GP' ou gpImport)
        for r in revisions:
            if r.get("createdVia") == "GP" or r.get("gpImport"):
                candidate_ids.append(r.get("revisionId"))
        
        # 2. Les 10 révisions les plus récentes
        for r in revisions[:10]:
            candidate_ids.append(r.get("revisionId"))
            
        # 3. Révisions historiques antérieures à l'éditeur web (createdVia is None)
        for r in revisions:
            if r.get("createdVia") is None:
                candidate_ids.append(r.get("revisionId"))
                
        # 4. Upload initial (toute première révision)
        if revisions:
            candidate_ids.append(revisions[-1].get("revisionId"))

        # Déduplication en préservant l'ordre de priorité
        seen = {latest_revision_id, None}
        ordered_candidates = []
        for cid in candidate_ids:
            if cid and cid not in seen:
                seen.add(cid)
                ordered_candidates.append(cid)

        # Test des candidats en parallèle par petits lots
        batch_size = 5
        for i in range(0, min(len(ordered_candidates), 25), batch_size):
            batch = ordered_candidates[i:i + batch_size]
            with ThreadPoolExecutor(max_workers=batch_size) as executor:
                results = list(executor.map(_fetch_revision, batch))
            
            res_dict = {rid: data for rid, data in results}
            for rid in batch:
                data = res_dict.get(rid)
                if data and data.get("source"):
                    candidate_url = data["source"]
                    if verify_source_url(candidate_url):
                        source_url = candidate_url
                        selected_rev_id = rid
                        rev_data = data
                        found = True
                        break
            if found:
                break

    if not source_url:
        song_title = meta_data.get("title", f"ID {song_id}")
        raise ValueError(
            f"Aucune source Guitar Pro (.gp/.gp5/.gp4/.gp3/.gpx) disponible pour « {song_title} ». "
            "Cette tablature a probablement été saisie sur l'éditeur Songsterr sans fichier importé."
        )

    return {
        "song_id": song_id,
        "revision_id": selected_rev_id,
        "artist": meta_data.get("artist"),
        "title": meta_data.get("title"),
        "source_url": source_url,
        "tracks": rev_data.get("tracks", []) if rev_data else [],
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
    
    url_path = urllib.parse.urlparse(details["source_url"]).path
    ext = Path(url_path).suffix.lower()
    if not ext:
        for candidate_ext in [".gp5", ".gp4", ".gp3", ".gpx", ".gp"]:
            if candidate_ext in details["source_url"].lower():
                ext = candidate_ext
                break
        else:
            ext = ".gp"
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
