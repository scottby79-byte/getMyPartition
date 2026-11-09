"""
Package `sources` — Connecteurs de partitions Guitar Pro.

Chaque module de ce package expose une interface uniforme :
  - SOURCE_ID   : str                           Identifiant technique unique.
  - SOURCE_LABEL: str                           Libellé affiché dans l'interface.
  - search_songs(query: str) -> list[dict]      Recherche de partitions.
  - get_song_gp_source(song_id) -> dict         Métadonnées + URL source.
  - download_gp_file(source_url, output_path)   Téléchargement du fichier .gp*.

Pour ajouter une nouvelle source :
  1. Créer un module dans ce répertoire qui respecte l'interface ci-dessus.
  2. L'importer dans app.py et l'ajouter à la liste SOURCES.
"""
