#!/usr/bin/env python3
"""
Source : GProTab (https://gprotab.net/).
Fournit des tablatures Guitar Pro (.gp, .gp3, .gp4, .gp5, .gpx) issues du catalogue communautaire GProTab.

Expose l'interface commune du package `sources` :
  - SOURCE_ID   : str
  - SOURCE_LABEL: str
  - search_songs(query: str) -> list[dict]
  - get_song_gp_source(song_id) -> dict
  - download_gp_file(source_url, output_path) -> Path
  - clean_filename(name: str) -> str
"""

import os
import re
import html
import urllib.request
import urllib.parse
import threading
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration & Constantes
# ---------------------------------------------------------------------------
SOURCE_ID    = "gprotab"
SOURCE_LABEL = "GProTab"

BASE_URL   = "https://gprotab.net"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
REFERER    = "https://gprotab.net/"

# Cache mémoire pour éviter de re-parser les pages et tablatures déjà consultées
_cache: dict[str, dict] = {}
_cache_lock = threading.Lock()
_CACHE_MAX = 200


def clean_filename(s: str) -> str:
    """Remplace les caractères interdits dans un nom de fichier pour le stockage local."""
    return re.sub(r'[^\w\s-]', '', str(s)).strip().replace(' ', '_')


def _fetch_html(url: str, timeout: int = 10) -> str:
    """Effectue une requête GET HTTP et retourne le contenu HTML décodé."""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Referer": REFERER,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
        }
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def _extract_tracks_from_bytes(data: bytes, ext: str) -> list[dict]:
    """
    Extrait les pistes du binaire Guitar Pro avec pyguitarpro (si compatible).
    En cas d'incompatibilité, renvoie une liste vide (alphaTab se chargera du décodage).
    """
    tracks = []
    if not data or len(data) < 30:
        return tracks

    tmp_path = None
    try:
        import guitarpro
        with tempfile.NamedTemporaryFile(suffix=ext or ".gp", delete=False) as tmp:
            tmp.write(data)
            tmp_path = tmp.name

        for enc in ("cp1252", "utf-8", "latin-1"):
            try:
                song = guitarpro.parse(tmp_path, encoding=enc)
                for idx, t in enumerate(getattr(song, "tracks", [])):
                    raw_name = getattr(t, "name", "")
                    if isinstance(raw_name, bytes):
                        name_str = raw_name.decode("utf-8", errors="replace")
                    else:
                        name_str = str(raw_name)
                    tracks.append({
                        "index": idx,
                        "name": name_str.strip() or f"Piste {idx + 1}"
                    })
                break
            except Exception:
                continue
    except Exception:
        pass
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    return tracks


# ---------------------------------------------------------------------------
# Interface publique
# ---------------------------------------------------------------------------

def search_songs(query: str) -> list[dict]:
    """
    Recherche des partitions sur GProTab.net.
    Effectue une recherche intelligente combinant recherche par morceau et par artiste
    pour maximiser la précision des résultats (tolérant aux requêtes 'Artiste - Titre').
    """
    clean_q = query.strip()
    if not clean_q:
        return []

    results = []
    seen = set()

    # Découpage si format "Artiste - Titre"
    parts = re.split(r'\s*[-–—]\s*', clean_q, maxsplit=1)
    sub_artist = parts[0].strip() if len(parts) > 1 else ''
    sub_title = parts[1].strip() if len(parts) > 1 else ''

    # Liste des requêtes de composition à tester
    queries_to_try = [clean_q]
    if sub_title and sub_title.lower() != clean_q.lower():
        queries_to_try.append(sub_title)
    else:
        words = clean_q.split()
        if len(words) >= 2:
            queries_to_try.append(' '.join(words[1:]))

    # 1. Recherche par titre de composition (type=song)
    for q_try in queries_to_try:
        url_song = f"{BASE_URL}/en/search?type=song&q={urllib.parse.quote(q_try)}"
        try:
            html_content = _fetch_html(url_song, timeout=8)
            # Motif de résultat GProTab:
            # <div class="tab search-tab">...<a href="/en/tabs/..." class="tab-band">Artiste</a>...<a href="/en/tabs/.../..." class="tab-name">Titre</a>
            matches = re.finditer(
                r'<div class=[\"\']tab search-tab[\"\']>.*?<a href=[\"\'](/en/tabs/[^/\"]+)[\"\'] class=[\"\']tab-band[\"\']>([^<]+)</a>\s*<a href=[\"\'](/en/tabs/[^/\"]+/[^/\"]+)[\"\'] class=[\"\']tab-name[\"\']>([^<]+)</a>',
                html_content, re.DOTALL
            )
            for m in matches:
                _, band_name, song_href, song_name = m.groups()
                clean_band = html.unescape(band_name.strip())
                clean_song = html.unescape(song_name.strip())

                # Si un artiste spécifique était demandé, filtrer
                if sub_artist and sub_artist.lower() not in clean_band.lower():
                    continue

                if song_href not in seen:
                    seen.add(song_href)
                    results.append({
                        "songId": song_href,
                        "artist": clean_band,
                        "title": clean_song,
                        "source": SOURCE_ID,
                        "tracks": []
                    })
        except Exception as e:
            pass

        if len(results) >= 15:
            break

    # 2. Si peu de résultats, recherche par nom d'artiste (type=artist)
    if len(results) < 6:
        artist_query = sub_artist or clean_q
        url_artist = f"{BASE_URL}/en/search?type=artist&q={urllib.parse.quote(artist_query)}"
        try:
            art_html = _fetch_html(url_artist, timeout=8)
            art_matches = re.findall(
                r'<ol class=[\"\']artists[\"\']>.*?<li>.*?<a href=[\"\'](/en/tabs/[^/\"]+)[\"\']>([^<]+)</a>',
                art_html, re.DOTALL
            )
            for art_href, art_name in art_matches[:3]:
                clean_art_name = html.unescape(art_name.strip())
                # Charger la page catalogue de l'artiste
                page_html = _fetch_html(f"{BASE_URL}{art_href}", timeout=8)
                songs_found = re.findall(
                    r'<a href=[\"\'](/en/tabs/[^/\"]+/[^/\"]+)[\"\'][^>]*>([^<]+)</a>',
                    page_html
                )
                for s_href, s_title in songs_found:
                    clean_s_title = html.unescape(s_title.strip())
                    target_filter = sub_title or (clean_q if clean_q.lower() != clean_art_name.lower() else '')
                    if target_filter and target_filter.lower() not in clean_s_title.lower():
                        continue

                    if s_href not in seen:
                        seen.add(s_href)
                        results.append({
                            "songId": s_href,
                            "artist": clean_art_name,
                            "title": clean_s_title,
                            "source": SOURCE_ID,
                            "tracks": []
                        })
                    if len(results) >= 20:
                        break
                if len(results) >= 20:
                    break
        except Exception:
            pass

    return results


def get_song_gp_source(song_id: str) -> dict:
    """
    Récupère les détails et l'URL source directe d'une tablature GProTab.
    `song_id` est le chemin d'accès relatif (ex: '/en/tabs/nirvana/about-a-girl' ou 'nirvana/about-a-girl').
    """
    clean_id = str(song_id).strip()
    if not clean_id.startswith("/"):
        clean_id = f"/en/tabs/{clean_id}" if not clean_id.startswith("en/tabs/") else f"/{clean_id}"

    # Vérification en cache mémoire
    with _cache_lock:
        if clean_id in _cache:
            return _cache[clean_id]

    tab_page_url = f"{BASE_URL}{clean_id}"
    page_html = _fetch_html(tab_page_url, timeout=10)

    # 1. Extraction de l'Artiste
    band_m = re.search(r'<td>Band</td>\s*<td>(.*?)</td>', page_html, re.I | re.DOTALL)
    if band_m:
        raw_band = re.sub(r'<[^>]*>', '', band_m.group(1)).strip()
        artist = html.unescape(raw_band)
    else:
        artist = "Inconnu"

    # 2. Extraction du Titre
    song_m = re.search(r'<td>Song</td>\s*<td>(.*?)</td>', page_html, re.I | re.DOTALL)
    if song_m:
        raw_song = re.sub(r'<[^>]*>', '', song_m.group(1)).strip()
        title = html.unescape(raw_song)
    else:
        title = "Partition"

    # 3. Format / extension du fichier
    type_m = re.search(r'<td>Tab file type</td>\s*<td>(.*?)</td>', page_html, re.I | re.DOTALL)
    if type_m:
        raw_ext = re.sub(r'<[^>]*>', '', type_m.group(1)).strip().lower()
        ext = f".{raw_ext}" if not raw_ext.startswith(".") else raw_ext
    else:
        ext = ".gp5"

    # 4. URL de téléchargement directe
    dl_m = re.search(r'<a[^>]+href=[\"\'](/en/tabs/[^/\"\'?]+/[^/\"\'?]+\?download)[\"\']', page_html, re.I)
    if dl_m:
        source_url = f"{BASE_URL}{dl_m.group(1)}"
    else:
        source_url = f"{tab_page_url}?download"

    # 5. Téléchargement préventif pour analyse des pistes instrumentales
    tracks = []
    try:
        req_dl = urllib.request.Request(
            source_url,
            headers={"User-Agent": USER_AGENT, "Referer": tab_page_url}
        )
        with urllib.request.urlopen(req_dl, timeout=12) as dl_resp:
            file_bytes = dl_resp.read()
            # Si le Content-Disposition indique une extension plus précise
            cd_hdr = dl_resp.headers.get("Content-Disposition", "")
            if "filename=" in cd_hdr:
                fn_match = re.search(r'filename=[\"\']?([^\"\';]+)', cd_hdr)
                if fn_match:
                    found_ext = Path(fn_match.group(1)).suffix.lower()
                    if found_ext:
                        ext = found_ext

            tracks = _extract_tracks_from_bytes(file_bytes, ext)
    except Exception:
        pass

    result = {
        "song_id": clean_id,
        "artist": artist,
        "title": title,
        "source_url": source_url,
        "source": SOURCE_ID,
        "ext": ext,
        "tracks": tracks,
    }

    # Mise en cache
    with _cache_lock:
        if len(_cache) >= _CACHE_MAX:
            _cache.pop(next(iter(_cache)))
        _cache[clean_id] = result

    return result


def download_gp_file(source_url: str, output_path: Path) -> Path:
    """
    Télécharge le fichier Guitar Pro depuis GProTab.net et l'enregistre sur le disque local.
    """
    req = urllib.request.Request(
        source_url,
        headers={
            "User-Agent": USER_AGENT,
            "Referer": REFERER,
        }
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        content = response.read()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(content)

    return output_path
