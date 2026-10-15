- Add search on GProTab (gprotab.net)   Un site communautaire gratuit et très épuré spécialisé dans le partage de partitions Guitar Pro.API officielle : Pas d'API REST formelle documentée. Accessibilité : La structure du site est très simple (URL prévisibles, formulaires légers). C'est l'un des sites les plus faciles à scraper de manière éthique pour rechercher des morceaux et télécharger les fichiers .gp5
- delete local file 
- repair suggestion
- add gp pro file in the supabase storage and add in a mogodb atlas => Create extract_mygtab.py qui respecte une interface commune
- creation d'un keepalive du storage et de la bdd
- keep_alive du conteneur avec https://cron-job.org/en/

Pour configurer et injecter vos variables de manière sécurisée de GitHub vers Render (via Docker), la méthode standard consiste à stocker les secrets dans les GitHub Actions Secrets, puis à les passer au conteneur lors du déploiement ou directement dans la configuration de l'hébergeur.Voici la démarche complète et sécurisée :

1.Configurer les secrets dans GitHub :

Étape 1.Pour que vos identifiants ne soient jamais exposés dans votre code source :Allez sur votre dépôt GitHub dans Settings > Secrets and variables > Actions.Cliquez sur New repository secret et ajoutez un par un vos secrets (ex: SUPABASE_URL, SUPABASE_KEY, SUPABASE_BUCKET, MONGO_URI).

2.Gérer les variables dans le Dockerfile :

Étape 2.Dans votre Dockerfile, les variables d'environnement ne doivent pas contenir de valeurs en dur. Vous devez simplement déclarer qu'elles sont attendues par l'application :

Dockerfile :

FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Déclare les variables d'environnement (valeurs vides par défaut)
ENV SUPABASE_URL=""
ENV SUPABASE_KEY=""
ENV SUPABASE_BUCKET=""
ENV MONGO_URI=""

EXPOSE 8080

CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:8080", "app:app"]

3.Transmettre les secrets lors du déploiement (GitHub Actions / Render) :
Étape 3.Selon la méthode que vous utilisez pour déployer sur Render :

Option A : Directement dans le tableau de bord Render (Recommandé pour un déploiement simple)Render gère nativement les secrets de façon sécurisée sans passer par le Dockerfile :Allez sur votre tableau de bord Render sur le service web concerné.Allez dans l'onglet Environment.Ajoutez vos variables (SUPABASE_URL, SUPABASE_KEY, etc.) avec leurs valeurs de production. Render les injectera automatiquement dans le conteneur, et votre code Python les récupérera sans modification via os.getenv("...").

Option B : Via un workflow GitHub Actions (si vous automatisez le déploiement)

Si vous utilisez une action GitHub pour pousser vers Render, vous passez les secrets stockés à l'étape 1 dans les variables d'environnement du workflow :

YAML
env:
  SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
  SUPABASE_KEY: ${{ secrets.SUPABASE_KEY }}
  SUPABASE_BUCKET: ${{ secrets.SUPABASE_BUCKET }}
  MONGO_URI: ${{ secrets.MONGO_URI }}

Une fois ces étapes en place, votre code qui utilise os.getenv("SUPABASE_URL") fonctionnera de manière parfaitement transparente et sécurisée, que ce soit en local (via le fichier .env) ou en production sur Render !