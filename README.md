# 🎸 GetMyPartition — Band Suite

Application web moderne (**PWA**), API REST Python et suite d'outils dédiée à la **recherche**, la **visualisation/écoute interactive** et le **téléchargement** de partitions multi-instruments au format **Guitar Pro** (`.gp`, `.gp3`, `.gp4`, `.gp5`, `.gpx`).

Conçue pour les musiciens et groupes en répétition ou sur scène, elle agrège plusieurs sources de tablatures (bibliothèque personnelle cloud et catalogues en ligne) dans une interface épurée, rapide et responsive.

---

## ✨ Fonctionnalités Principales

### 🔍 Recherche multi-sources intelligente
* **Agrégation en parallèle** : Interrogation simultanée de plusieurs fournisseurs (Songsterr, bibliothèque privée MongoDB/Supabase, etc.).
* **Tolérance aux accents et apostrophes** : Recherche insensible aux accents (`celine` $\leftrightarrow$ `Céline`), apostrophes droites `'` ou typographiques `'`, tirets et espaces.
* **Filtrage strict Songsterr** : Détection et élimination préalable des tablatures sans fichier binaire Guitar Pro.
* **Historique et suggestions** : Mémorisation asynchrone des recherches fréquentes dans MongoDB (`LastSearch`) et tags de suggestion cliquables.

### 🎼 Lecteur et visualiseur interactif (alphaTab)
* **Rendu HTML5 Canvas 2D accéléré** : Affichage fluide de la notation musicale et tablature, avec défilement automatique optimisé.
* **Synthétiseur audio intégré** : Lecture sonore multi-pistes réaliste via banque de sons SoundFont (`sonivox.sf2`).
* **Mixage et sélection des instruments** : Sélection de n'importe quelle piste (Guitare Solo, Rythmique, Basse, Batterie, Chant, Claviers...).
* **Outils d'entraînement** : Réglage précis de la vitesse de lecture (0.5x à 1.5x), métronome intégré, lecture en boucle (looping), barre de progression cliquable.
* **Options d'affichage** : Profil standard (portée + tablature), tablature seule, ou portée classique seule.
* **Mode Scène & Répétition** :
  * Thème clair / sombre instantané.
  * Mode plein écran.
  * **Screen Wake Lock API** : Empêche automatiquement la mise en veille de l'écran sur smartphone ou tablette.
* **Téléchargement direct** : Sauvegarde immédiate de la partition ouverte avec son vrai nom d'origine et son extension native exacte.

### 💾 Gestion locale des téléchargements
* Consultation des fichiers téléchargés dans le dossier local `download/`.
* Informations complètes : format, taille en Ko/Mo, date de modification.
* Boutons d'écoute directe ou de retéléchargement en un clic.

### 📱 Progressive Web App (PWA)
* Application installable sur Android, iOS, Windows, macOS et Linux via le navigateur.
* Service Worker (`sw.js`), icônes dédiées et `manifest.json`.

---

## 🏗️ Architecture & Sources

L'application repose sur une architecture modulaire où chaque source implémente une interface Python uniforme dans le package `sources/` :
* `search_songs(query: str) -> list[dict]`
* `get_song_gp_source(song_id) -> dict`
* `download_gp_file(source_url, output_path) -> Path`

```
┌────────────────────────────────────────────────────────┐
│               Interface Web PWA (HTML5 / JS)            │
│            Lecteur audio & tablature alphaTab          │
└───────────────────────────▲────────────────────────────┘
                            │ API REST (/api/*)
┌───────────────────────────┴────────────────────────────┐
│               Serveur WSGI Flask (app.py)              │
│       ThreadPoolExecutor & Encodage RFC 5987 UTF-8     │
└─────────────▲────────────────────────────▲─────────────┘
              │                            │
   ┌──────────┴──────────┐      ┌──────────┴────────────┐
   │  sources/           │      │  sources/             │
   │  songsterr.py       │      │  myguitarpro.py       │
   │  (Catalogue Web)    │      │  (Bibliothèque Privée)│
   └──────────▲──────────┘      └──────────▲────────────┘
              │                            │
     Songsterr REST API          MongoDB Atlas + Supabase
    Validation Revisions               Storage (S3)
```

1. **`sources/songsterr.py`** : Recherche sur Songsterr avec validation de révision. Si la dernière version n'a pas de fichier binaire, le script explore l'historique pour récupérer la dernière révision Guitar Pro valide. Un cache mémoire thread-safe assure l'ouverture instantanée des partitions validées.
2. **`sources/myguitarpro.py`** : Recherche plein texte avec regex floue sur MongoDB Atlas (métadonnées, pistes, artistes, titres, noms de fichiers) et téléchargement des binaires depuis le bucket privé Supabase Storage via URLs signées temporaires.

---

## 🛠️ Installation & Lancement Local

### Prérequis
* Python 3.11 ou 3.12
* Accès internet pour les dépendances et les services cloud (MongoDB Atlas / Supabase)

### 1. Cloner le projet et configurer l'environnement virtuel
```bash
git clone https://github.com/votre-compte/getMyPartition.git
cd getMyPartition

python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 2. Configuration des variables d'environnement
Créez un fichier `.env` à la racine :

```ini
# Port du serveur Flask en local
PORT=8080

# Keep-Alive (secondes entre chaque ping de réveil cloud)
KEEP_ALIVE_CHECK=600

# Supabase Storage (Privé)
SUPABASE_URL=https://votre-projet.supabase.co
SUPABASE_KEY=votre_cle_api_service_role
SUPABASE_BUCKET=GetMyPartitionStorage

# MongoDB Atlas
MONGO_URI=mongodb+srv://utilisateur:motdepasse@cluster.mongodb.net/?appName=votre-app
MONGO_DBNAME=GetMyPartition
MONGO_COLLECTION_GPTAB_NAME=GuitarProTab
MONGO_COLLECTION_SEARCH_NAME=LastSearch
```

> **⚠️ Sécurité** : Ne committez jamais votre `.env` ou `production.env`. Ils sont ignorés par `.gitignore`.

### 3. Démarrer le serveur
```bash
python3 app.py
```
L'application est disponible sur : **[http://localhost:8080](http://localhost:8080)**

### 4. Lancer les tests unitaires (Non-régression & Bouchons API)
Une suite de 24 tests unitaires couvre l'intégralité des endpoints avec des bouchons pour Songsterr, MongoDB et Supabase :
```bash
python3 -m unittest discover -s tests -v
```


---

## 📡 Endpoints de l'API REST

| Méthode | Endpoint | Paramètres | Description |
| :--- | :--- | :--- | :--- |
| `GET` | `/` | — | Interface web PWA principale (`index.html`). |
| `GET` | `/api/search` | `q=...` ou `artist=...&title=...` | Recherche en parallèle sur toutes les sources actives. |
| `GET` | `/api/recent-searches`| — | Retourne les 20 dernières recherches enregistrées dans MongoDB. |
| `GET` | `/api/song` | `id=...&source=...` | Métadonnées détaillées, liste des instruments et URL de la partition. |
| `GET` | `/api/check` | `id=...&source=...` | Vérifie la disponibilité d'une partition Guitar Pro sans la télécharger. |
| `POST` | `/api/download` | JSON : `{"id": "...", "source": "..."}` | Télécharge le fichier dans `download/` et renvoie ses informations. |
| `GET` | `/api/download` | `id=...&source=...&direct=1` | Télécharge et renvoie le flux binaire directement en pièce jointe. |
| `GET` | `/api/tab-file` | `id=...&source=...[&download=1]` | Sert le binaire (flux `inline` pour alphaTab ou `attachment` pour enregistrement). |
| `GET` | `/api/local-files` | — | Liste des fichiers Guitar Pro présents dans le dossier `download/`. |
| `GET` | `/api/local-download` | `file=...` | Télécharge un fichier présent localement dans `download/`. |
| `GET` | `/api/healthcheck` | — | Endpoint de monitoring pour `cron-job.org` ou Uptime Kuma (renvoie `200 OK`). |

---

## 📦 Scripts d'Administration & d'Ingestion (`tools/`)

Les scripts d'administration sont regroupés dans le dossier `tools/` et s'exécutent **depuis la racine du projet** (le `.env` est résolu automatiquement). Ils ne sont **pas** inclus dans l'image Docker de production.

### Ingestion massive locale vers le Cloud : `tools/_import_gptab.py`
Scanne récursivement un répertoire local contenant des partitions (`.gp`, `.gp3`, `.gp4`, `.gp5`, `.gpx`), analyse les pistes avec `pyguitarpro` (support multi-encodage CP1252 / UTF-8 / Latin-1), normalise les clés ASCII pour Supabase Storage (normalisation NFKD), et synchronise les métadonnées sur MongoDB Atlas avec gestion anti-doublon.

```bash
python3 tools/_import_gptab.py
```

### Migration et indexation des pistes : `tools/_tag_gptab.py`
Parcourt tous les documents déjà stockés dans MongoDB, télécharge le fichier depuis Supabase, extrait l'intégralité des pistes instrumentales et met à jour le tableau `metadata.tracks`.

```bash
python3 tools/_tag_gptab.py
```

### Test de connexion MongoDB : `tools/_testConn.py`
Vérifie la connexion à MongoDB Atlas et affiche les bases de données accessibles.

```bash
python3 tools/_testConn.py
```

---

## 🐳 Déploiement en Production (Docker & Render)

Le projet est livré avec un [Dockerfile](Dockerfile) sécurisé basé sur **Python 3.12-slim** et servi par le serveur WSGI **Gunicorn** (multi-workers et multi-threads).

### Déploiement sur Render (Web Service)
1. Poussez votre code sur votre dépôt GitHub / GitLab.
2. Sur **[Render Dashboard](https://dashboard.render.com/)**, créez un **New Web Service** connecté à votre dépôt.
3. Render détecte automatiquement l'environnement `Docker`.
4. Dans l'onglet **Environment**, ajoutez vos variables sécurisées :
   * `SUPABASE_URL`
   * `SUPABASE_KEY`
   * `SUPABASE_BUCKET`
   * `MONGO_URI`
   * `MONGO_DBNAME`
   * `MONGO_COLLECTION_GPTAB_NAME`
   * `MONGO_COLLECTION_SEARCH_NAME`
   * `KEEP_ALIVE_CHECK` (optionnel, ex: `600`)
5. Déployez !

### Prévention de la mise en veille sur plan gratuit (Keep-Alive)
Sur les offres gratuites (type Render Free), le conteneur s'endort après 15 minutes d'inactivité. Deux mécanismes conjoints sont en place :
1. **Thread interne `background_keep_alive`** : Ping périodique de MongoDB et Supabase pour maintenir les pools de connexion chauds.
2. **Ping externe gratuit** : Configurez une requête HTTP `GET` toutes les 10 minutes sur `https://votre-app.onrender.com/api/healthcheck` via **[cron-job.org](https://cron-job.org/)**.

---

## 📁 Structure du Projet

```text
getMyPartition/
├── app.py                    # API REST Flask & serveur WSGI (Keep-alive, routes)
├── sources/                  # Package Python — connecteurs de sources de partitions
│   ├── __init__.py           # Documentation de l'interface commune
│   ├── songsterr.py          # Connecteur Songsterr (recherche, validation, cache)
│   └── myguitarpro.py        # Connecteur bibliothèque (MongoDB Atlas + Supabase)
├── images/                   # Icônes PWA
│   ├── icon-192.png          # Icône PWA 192x192
│   ├── icon-512.png          # Icône PWA 512x512
│   ├── ico_192x192.xcf       # Source GIMP 192x192
│   └── ico_512x512.xcf       # Source GIMP 512x512
├── tools/                    # Scripts d'administration (non déployés en production)
│   ├── _import_gptab.py      # Ingestion massive locale -> Supabase + MongoDB
│   ├── _tag_gptab.py         # Rétro-tagging des pistes audio
│   └── _testConn.py          # Test de connexion MongoDB
├── tests/                    # Tests unitaires & bouchons API (mocking)
│   ├── __init__.py
│   └── test_api.py           # 24 tests unitaires déterministes et isolés
├── index.html                # Interface PWA complète & intégration lecteur alphaTab
├── sw.js                     # Service Worker pour l'installation PWA
├── manifest.json             # Manifeste d'application PWA (icônes, thème, nom)
├── download/                 # Dossier de stockage des partitions téléchargées (local)
├── requirements.txt          # Dépendances Python de production
├── Dockerfile                # Conteneur de production sécurisé non-root
├── render.yaml               # Blueprint de déploiement Render
└── README.md                 # Documentation du projet
```

---

## ➕ Ajouter une nouvelle source

1. Créer `sources/ma_nouvelle_source.py` en respectant l'interface :
   ```python
   SOURCE_ID    = "ma-source"       # identifiant unique
   SOURCE_LABEL = "Ma Source"       # libellé dans l'UI

   def search_songs(query: str) -> list[dict]: ...
   def get_song_gp_source(song_id) -> dict: ...
   def download_gp_file(source_url, output_path) -> Path: ...
   def clean_filename(name: str) -> str: ...
   ```
2. Dans `app.py`, importer le module et l'ajouter dans `SOURCES` :
   ```python
   from sources import ma_nouvelle_source
   SOURCES = [songsterr, myguitarpro, ma_nouvelle_source]
   ```
3. C'est tout — l'interface et l'API s'adaptent automatiquement.

---

## 📄 Licence
Ce projet est sous licence [MIT](LICENSE).
