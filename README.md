# 🎸 GetMyPartition — Band Suite

Application web moderne (**PWA**), API REST Python et suite d'outils dédiée à la **recherche**, la **visualisation/écoute interactive** et le **téléchargement** de partitions multi-instruments au format **Guitar Pro** (`.gp`, `.gp3`, `.gp4`, `.gp5`, `.gpx`).

Conçue pour les musiciens et groupes en répétition ou sur scène, elle agrège plusieurs sources de tablatures (bibliothèque personnelle cloud et catalogues en ligne) dans une interface épurée, rapide et responsive.

---

## ✨ Fonctionnalités Principales

### 🔍 Recherche multi-sources intelligente
* **Agrégation en parallèle** : Interrogation simultanée de plusieurs fournisseurs (Songsterr, bibliothèque privée MongoDB/Supabase, etc.).
* **Tolérance aux accents et apostrophes** : Recherche insensible aux accents (`celine` $\leftrightarrow$ `Céline`), apostrophes droites `'` ou typographiques `’`, tirets et espaces.
* **Filtrage strict Songsterr** : Détection et élimination préalable des tablatures sans fichier binaire Guitar Pro (saisies directement sur l'éditeur web ou générées sans import).
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
  * **Screen Wake Lock API** : Empêche automatiquement la mise en veille de l'écran sur smartphone ou tablette pendant l'utilisation du player.
* **Téléchargement direct** : Sauvegarde immédiate de la partition ouverte avec son vrai nom d'origine et son extension native exacte (`.gp`, `.gp3`, `.gp4`, `.gp5`, `.gpx`).

### 💾 Gestion locale des téléchargements
* Consultation des fichiers téléchargés dans le dossier local `download/`.
* Informations complètes : format, taille en Ko/Mo, date de modification.
* Boutons d'écoute directe ou de retéléchargement en un clic.

### 📱 Progressive Web App (PWA)
* Application installable sur Android, iOS, Windows, macOS et Linux via le navigateur.
* Service Worker (`sw.js`), icônes dédiées et `manifest.json`.

---

## 🏗️ Architecture & Sources

L'application repose sur une architecture modulaire où chaque source implémente une interface Python uniforme :
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
   ┌──────────┴──────────┐      ┌──────────┴──────────┐
   │    songsterr.py     │      │   myguitarpro.py    │
   │   (Catalogue Web)   │      │ (Bibliothèque Privée│
   └──────────▲──────────┘      └──────────▲──────────┘
              │                            │
      Songsterr REST API          MongoDB Atlas + Supabase
     Validation Revisions               Storage (S3)
```

1. **`songsterr.py`** : Recherche sur Songsterr avec validation de révision. Si la dernière version n'a pas de fichier binaire, le script explore l'historique pour récupérer la dernière révision Guitar Pro valide. Un cache mémoire thread-safe assure l'ouverture instantanée des partitions validées.
2. **`myguitarpro.py`** : Recherche plein texte avec regex floue sur MongoDB Atlas (métadonnées, pistes, artistes, titres, noms de fichiers) et téléchargement des binaires depuis le bucket privé Supabase Storage via URLs signées temporaires.

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
Créez un fichier `.env` ou `production.env` à la racine :

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

### 3. Démarrer le serveur
```bash
python3 app.py
```
L'application est disponible sur : **[http://localhost:8080](http://localhost:8080)**

---

## 📡 Endpoints de l'API REST

| Méthode | Endpoint | Paramètres | Description |
| :--- | :--- | :--- | :--- |
| `GET` | `/` | — | Interface web PWA principale (`index.html`). |
| `GET` | `/api/search` | `q=...` ou `artist=...&title=...` | Recherche en parallèle sur toutes les sources actives (Songsterr, bibliothèque...). |
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

## 📦 Scripts d'Administration & d'Ingestion

### Ingestion massive locale vers le Cloud : `_import_gptab.py`
Scanne récursivement un répertoire local contenant des partitions (`.gp`, `.gp3`, `.gp4`, `.gp5`, `.gpx`), analyse les pistes avec `pyguitarpro` (support multi-encodage CP1252 / UTF-8 / Latin-1), normalise les clés ASCII pour Supabase Storage (normalisation NFKD anti-`InvalidKey`), et synchronise les métadonnées sur MongoDB Atlas avec gestion anti-doublon.

```bash
python3 _import_gptab.py
```

### Migration et indexation des pistes : `_tag_gptab.py`
Parcourt tous les documents déjà stockés dans MongoDB, télécharge le fichier depuis Supabase, extrait l'intégralité des pistes instrumentales et met à jour le tableau `metadata.tracks`.

```bash
python3 _tag_gptab.py
```

---

## 🐳 Déploiement en Production (Docker & Render)

Le projet est livré avec un [Dockerfile](file:///media/florent/Data/workspaces/WK_VS_Code/getMyPartition/Dockerfile) sécurisé basé sur **Python 3.12-slim** et servi par le serveur WSGI **Gunicorn** (multi-workers et multi-threads).

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
├── app.py                  # API REST Flask & serveur WSGI (Keep-alive, routes)
├── songsterr.py            # Connecteur Songsterr (recherche, validation, cache)
├── myguitarpro.py          # Connecteur bibliothèque (MongoDB Atlas + Supabase)
├── index.html              # Interface PWA complète & intégration lecteur alphaTab
├── sw.js                   # Service Worker pour l'installation PWA
├── manifest.json           # Manifeste d'application PWA (icônes, thème, nom)
├── icon-192.png            # Icône PWA 192x192
├── icon-512.png            # Icône PWA 512x512
├── _import_gptab.py        # Script d'ingestion massive locale -> Supabase + Mongo
├── _tag_gptab.py           # Script de rétro-tagging des pistes audio
├── download/               # Dossier de stockage des partitions téléchargées
├── requirements.txt        # Dépendances Python de production
├── Dockerfile              # Conteneur de production sécurisé non-root
├── render.yaml             # Blueprint de déploiement Render
└── README.md               # Documentation du projet
```

---

## 📄 Licence
Ce projet est sous licence [MIT](file:///media/florent/Data/workspaces/WK_VS_Code/getMyPartition/LICENSE).
