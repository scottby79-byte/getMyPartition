# 🎸 Extracteur de Partitions Guitar Pro (.gp5)

Application autonome (front-end web + back-end API Python) permettant de rechercher et télécharger directement des partitions multi-instruments au format **Guitar Pro (.gp5 / .gp)** pour le groupe de musique.

---

## 🌐 1. Origine des Fichiers GP5 & Fonctionnement Technique

Les fichiers sont extraits directement depuis les serveurs de **Songsterr** (`https://gp.songsterr.com/`).

### Pourquoi et comment ?
- Les tablatures "Pro" sur Ultimate Guitar sont souvent verrouillées derrière un abonnement payant, mais la communauté des musiciens partage généralement les mêmes fichiers sur Songsterr.
- Contrairement à Ultimate Guitar, Songsterr dispose d'une API publique qui permet de retrouver le fichier source original :
  1. **Recherche de morceau** : Interrogation de `https://www.songsterr.com/api/songs?pattern=<artiste>+<titre>` pour récupérer la liste des résultats et leur `songId`.
  2. **Métadonnées** : Récupération du `revisionId` le plus récent via `https://www.songsterr.com/api/meta/<songId>`.
  3. **URL source Guitar Pro** : Appel à `https://www.songsterr.com/api/revision/<revisionId>` qui contient le lien direct vers le fichier binaire `.gp5` ou `.gp`.
  4. **Téléchargement** : Récupération du binaire avec les en-têtes HTTP adéquats (`User-Agent` et `Referer: https://www.songsterr.com/`).

---

## 🚀 2. Lancer l'Interface Web (Front + Back)

L'application est développée en **100% Python standard** (**zéro dépendance externe**, aucun `pip install` ou environnement virtuel nécessaire).

### Démarrage du serveur :
```bash
python3 app.py
```
*(Optionnel : vous pouvez spécifier un autre port, par exemple `python3 app.py 9000`)*

### Accès à l'application :
Ouvrez votre navigateur web sur :  
👉 **[http://localhost:8080](http://localhost:8080)**

---

## ✨ 3. Fonctionnalités de l'Interface Web

- 🔍 **Recherche par Artiste et Titre** : Formulaire avec suggestions rapides (ex: *Izïa*, *Muse*, *Nirvana*, *RHCP*).
- 🏷️ **Badges d'instruments** : Visualisation instantanée des pistes présentes dans la partition (🎸 Guitare, 🎸 Basse, 🥁 Batterie, 🎤 Chant, 🎹 Clavier).
- ⬇️ **Téléchargement en un clic** :
  - Sauvegarde immédiate dans votre dossier local `partitions/`.
  - Déclenchement automatique du téléchargement dans votre navigateur web.
- 📁 **Gestionnaire de partitions locales** : Liste toutes les partitions `.gp5` déjà présentes dans le dossier avec leur taille, date d'ajout et bouton de retéléchargement rapide.
- 🎧 **Lien vers le lecteur Songsterr** : Bouton pour ouvrir le lecteur interactif en ligne si vous souhaitez pré-écouter le morceau.

---

## 🔌 4. Endpoints de l'API REST (Backend Python)

Le serveur `app.py` communique avec l'interface web via des appels API asynchrones (`fetch`) :

| Méthode | Endpoint | Paramètres | Description |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/search` | `?artist=...&title=...` ou `?q=...` | Recherche des morceaux correspondants |
| `GET` | `/api/song` | `?id=<songId>` | Récupère les métadonnées et pistes d'un morceau |
| `POST` | `/api/download` | Body JSON : `{"id": <songId>}` | Télécharge et enregistre la partition sur le disque local |
| `GET` | `/api/local-files` | *(aucun)* | Liste les fichiers `.gp5` / `.gp` présents dans le dossier |
| `GET` | `/api/local-download` | `?file=<nom_du_fichier>` | Permet de retélécharger un fichier local |

---

## 💻 5. Utilisation en Ligne de Commande (CLI)

Si vous préférez télécharger une partition directement sans ouvrir le navigateur :

```bash
python3 extract_partition.py "<Artiste>" "<Titre>" [dossier_destination]
```

### Exemple :
```bash
python3 extract_partition.py "Izia" "Let Me Alone"
```

Le fichier sera automatiquement téléchargé sous le nom `IZIA_Let_Me_Alone.gp5`.

---

## 🐳 6. Déploiement sur Render (onrender.com) avec Gunicorn

Le projet est packagé pour la production avec **Gunicorn** (serveur WSGI multi-workers et multi-threads) :
- `gunicorn --bind 0.0.0.0:${PORT} --workers 2 --threads 4 --timeout 60 app:app`

### Étapes de déploiement :
1. Poussez ce dossier sur un dépôt Git (**GitHub** ou **GitLab**).
2. Rendez-vous sur votre dashboard **[Render](https://dashboard.render.com/)**.
3. Cliquez sur **New +** ➔ **Web Service**.
4. Sélectionnez votre dépôt Git.
5. Render détectera automatiquement le **Dockerfile** :
   - **Environment** : `Docker`
   - **Plan** : `Free`
   - Le port `$PORT` (10000 par défaut sur Render) est pris en charge automatiquement.
6. Cliquez sur **Deploy Web Service** ! En 1 à 2 minutes, votre application sera accessible en ligne (ex: `https://votre-app.onrender.com`).

---

## 📂 7. Structure des Fichiers

```text
ThursdayMadness/partitions/
├── Dockerfile              # Image Docker avec Gunicorn multi-workers
├── requirements.txt        # Dépendances de production (Flask, Gunicorn)
├── .dockerignore           # Exclusions pour un build Docker propre et léger
├── render.yaml             # Blueprint de configuration pour Render
├── app.py                  # Application WSGI Flask (compatible Gunicorn & local)
├── index.html              # Interface utilisateur web moderne et responsive
├── extract_partition.py    # Script CLI & module d'extraction Songsterr
├── README.md               # Cette documentation
└── IZIA_Let_Me_Alone.gp5   # Fichier Guitar Pro extrait (43 Ko)
```
