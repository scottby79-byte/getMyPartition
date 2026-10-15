# Image de base légère et sécurisée
FROM python:3.12-slim

# Configuration de l'environnement Python & port par défaut Render
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=10000

# Répertoire de travail
WORKDIR /app

# Création d'un utilisateur non-root pour la sécurité
RUN groupadd -g 1000 appgroup && \
    useradd -u 1000 -g appgroup -s /bin/sh -m appuser

# Déclare les variables d'environnement (valeurs vides par défaut)
ENV KEEP_ALIVE_CHECK=""
ENV SUPABASE_URL=""
ENV SUPABASE_KEY=""
ENV SUPABASE_BUCKET=""
ENV MONGO_URI=""
ENV MONGO_DBNAME=""
ENV MONGO_COLLECTION_GPTAB_NAME=""

# Installation des dépendances de production (Flask + Gunicorn)
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copie des fichiers applicatifs
COPY app.py songsterr.py myguitarpro.py index.html ./

# Attribution des droits sur le dossier de travail
RUN chown -R appuser:appgroup /app

# Exécution sous l'utilisateur non-root
USER appuser

# Exposition du port (Render mappe automatiquement $PORT)
EXPOSE 10000

# Lancement de l'application avec le serveur WSGI Gunicorn
CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT:-10000} --workers 2 --threads 4 --timeout 60 --access-logfile - --error-logfile - app:app"]
