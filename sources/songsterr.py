#!/usr/bin/env python3
"""
Script d'extraction de partitions Guitar Pro (.gp / .gp5 / .gp4 / .gp3 / .gpx) via Songsterr.
Prend en charge la recherche instantanée et la reconstruction fidèle en binaire .gp5
via les données de notes CDN et la bibliothèque PyGuitarPro.
"""

import io
import sys
import json
import gzip
import re
import threading
import urllib.request
import urllib.parse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import guitarpro
from sources import songsterr_convert

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0"
SONGSTERR_REFERER = "https://www.songsterr.com/"

# Caches mémoire pour maximiser la réactivité et éviter les requêtes répétées
_CACHE_MAX_SIZE = 500
_details_cache: dict[int, dict] = {}
_details_cache_lock = threading.Lock()

_gp5_bytes_cache: dict[int, tuple[bytes, str]] = {}
_gp5_bytes_lock = threading.Lock()

# Host buckets CDN CloudFront pour les données de notes Songsterr
STAGE_HOST = "d3d3l6a6rcgkaf"
NORMAL_HOSTS = ["dqsljvtekg760", "d34shlm8p2ums2", "d3cqchs6g3b5ew"]
LEGACY_HOSTS = ["d3rrfvx08uyjp1", "dodkcbujl0ebx", "dj1usja78sinh"]

# Identifiants de source — requis par l'interface commune (app.py)
SOURCE_ID    = "songsterr"
SOURCE_LABEL = "Songsterr"


def _cache_get(song_id: int):
    with _details_cache_lock:
        return _details_cache.get(song_id)


def _cache_set(song_id: int, details: dict):
    with _details_cache_lock:
        if len(_details_cache) >= _CACHE_MAX_SIZE:
            keys_to_remove = list(_details_cache.keys())[:100]
            for k in keys_to_remove:
                _details_cache.pop(k, None)
        _details_cache[song_id] = details


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


def _part_url(image: str, song_id: int, revision_id: int, part_id: int, attempt: int = 0) -> str:
    """Construit l'URL CloudFront pour récupérer le JSON d'une piste instrumentale."""
    if image and image.endswith("-stage"):
        host = STAGE_HOST
    elif image:
        host = NORMAL_HOSTS[attempt % len(NORMAL_HOSTS)]
    else:
        host = LEGACY_HOSTS[attempt % len(LEGACY_HOSTS)]
        return f"https://{host}.cloudfront.net/part/{revision_id}/{part_id}"
    return f"https://{host}.cloudfront.net/{song_id}/{revision_id}/{image}/{part_id}.json"


def _fetch_part(song_id: int, revision_id: int, image: str, part_id: int) -> dict | None:
    """Télécharge et décompresse le JSON d'une piste, en testant plusieurs CDN en cas d'erreur."""
    for attempt in range(3):
        url = _part_url(image, song_id, revision_id, part_id, attempt)
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": USER_AGENT, "Accept": "*/*", "Accept-Encoding": "gzip"}
            )
            with urllib.request.urlopen(req, timeout=12) as resp:
                data = resp.read()
            if data[:2] == b"\x1f\x8b":
                data = gzip.decompress(data)
            return json.loads(data.decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code not in (403, 404, 500, 502, 503):
                raise
        except Exception:
            pass
    return None


def search_songs(query: str) -> list:
    """
    Recherche instantanée des morceaux sur Songsterr par mot-clé (artiste et/ou titre).
    Filtre les morceaux disposant d'un lecteur et de pistes actives.
    """
    encoded_query = urllib.parse.quote(query.strip())
    url = f"https://www.songsterr.com/api/songs?pattern={encoded_query}"
    
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Referer": SONGSTERR_REFERER}
    )
    
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception:
        return []

    if not isinstance(data, list):
        return []

    results = []
    for song in data:
        if song.get("hasPlayer") and song.get("tracks"):
            results.append({
                "songId": song.get("songId"),
                "artist": song.get("artist"),
                "title": song.get("title"),
                "source": SOURCE_ID,
                "tracks": song.get("tracks", []),
            })
    return results


def get_song_gp_source(song_id: int | str) -> dict:
    """
    Récupère les métadonnées Songsterr et prépare la résolution du fichier .gp5.
    """
    try:
        numeric_id = int(song_id)
    except (ValueError, TypeError):
        numeric_id = song_id

    cached = _cache_get(numeric_id)
    if cached:
        return cached

    meta_url = f"https://www.songsterr.com/api/meta/{numeric_id}"
    req_meta = urllib.request.Request(
        meta_url,
        headers={"User-Agent": USER_AGENT, "Referer": SONGSTERR_REFERER}
    )
    with urllib.request.urlopen(req_meta, timeout=10) as response:
        meta_data = json.loads(response.read().decode("utf-8"))

    res = {
        "song_id": numeric_id,
        "revision_id": meta_data.get("revisionId"),
        "artist": meta_data.get("artist"),
        "title": meta_data.get("title"),
        "source_url": f"https://www.songsterr.com/api/meta/{numeric_id}",
        "ext": ".gp5",
        "tracks": meta_data.get("tracks", []),
        "reconstruct": True,
    }
    _cache_set(numeric_id, res)
    return res


def get_file_bytes(song_id: int | str) -> tuple[bytes, str]:
    """
    Génère ou récupère en cache le fichier Guitar Pro (.gp5) reconstruit depuis les pistes Songsterr.
    Retourne (content_bytes, filename).
    """
    try:
        numeric_id = int(song_id)
    except (ValueError, TypeError):
        numeric_id = song_id

    with _gp5_bytes_lock:
        if numeric_id in _gp5_bytes_cache:
            return _gp5_bytes_cache[numeric_id]

    meta_url = f"https://www.songsterr.com/api/meta/{numeric_id}"
    req = urllib.request.Request(meta_url, headers={"User-Agent": USER_AGENT, "Referer": SONGSTERR_REFERER})
    with urllib.request.urlopen(req, timeout=10) as resp:
        meta = json.loads(resp.read().decode("utf-8"))

    revision_id = meta.get("revisionId")
    image = meta.get("image")
    tracks = meta.get("tracks", [])

    def _fetch_idx(idx):
        return _fetch_part(numeric_id, revision_id, image, idx)

    # Téléchargement parallèle des JSON des différentes pistes
    with ThreadPoolExecutor(max_workers=min(max(len(tracks), 1), 8)) as pool:
        parts = list(pool.map(_fetch_idx, range(len(tracks))))

    # Conversion en modèle Guitar Pro (.gp5)
    song = songsterr_convert.build_song(meta, parts)

    bio = io.BytesIO()
    guitarpro.write(song, bio)
    content = bio.getvalue()

    artist_clean = clean_filename(meta.get("artist") or "Artist")
    title_clean = clean_filename(meta.get("title") or "Title")
    filename = f"{artist_clean}_{title_clean}.gp5"

    with _gp5_bytes_lock:
        if len(_gp5_bytes_cache) >= 100:
            _gp5_bytes_cache.pop(next(iter(_gp5_bytes_cache)))
        _gp5_bytes_cache[numeric_id] = (content, filename)

    return content, filename


def download_gp_file(source_url: str, output_path: Path) -> Path:
    """Télécharge ou génère le fichier Guitar Pro vers output_path."""
    # 1. Si l'URL pointe directement vers un binaire (.gp, .gp5...)
    if str(source_url).endswith((".gp", ".gp5", ".gp4", ".gp3", ".gpx")):
        try:
            req = urllib.request.Request(
                source_url,
                headers={"User-Agent": USER_AGENT, "Referer": SONGSTERR_REFERER}
            )
            with urllib.request.urlopen(req, timeout=15) as response:
                content = response.read()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(content)
            return output_path
        except Exception:
            pass

    # 2. Sinon, extraction du songId et reconstruction .gp5
    song_id = None
    m = re.search(r'/(\d+)(?:[^\d]|$)', str(source_url))
    if m:
        song_id = int(m.group(1))

    if song_id:
        content, _ = get_file_bytes(song_id)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(content)
        return output_path

    raise ValueError(f"Impossible de télécharger la partition pour l'URL : {source_url}")


def search_and_download(artist: str, title: str, output_dir: Path = Path(".")) -> dict:
    """Recherche un morceau par artiste et titre, puis télécharge le premier résultat."""
    query = f"{artist} {title}".strip()
    results = search_songs(query)
    
    if not results:
        raise RuntimeError(f"Aucun morceau trouvé pour la recherche : '{query}'")
    
    first = results[0]
    song_id = first["songId"]
    details = get_song_gp_source(song_id)
    
    filename = f"{clean_filename(details['artist'])}_{clean_filename(details['title'])}.gp5"
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
        print(f"   Fichier : {res['saved_path']}")
    except Exception as e:
        print(f"❌ Erreur : {e}")
        sys.exit(1)
