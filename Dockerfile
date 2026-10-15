# Image de base légère et sécurisée
FROM python:3.12-slim

# Configuration de l'environnement Python & port par défaut Render
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=10000

# Répertoire de travail
WORKDIR /app

# Installation des certificats SSL racines (indispensable pour les handshakes SSL avec MongoDB Atlas et Supabase)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Mise à jour de pip et certifi pour garantir des liaisons TLS robustes
RUN pip install --no-cache-dir --upgrade pip certifi

# Création d'un utilisateur non-root pour la sécurité
RUN groupadd -g 1000 appgroup && \
    useradd -u 1000 -g appgroup -s /bin/sh -m appuser

# Installation des dépendances de production (Flask + Gunicorn)
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copie des fichiers applicatifs (assurez-vous que le nom du module correspond bien à vos fichiers, ex: myguitarpro.py)
COPY app.py songsterr.py myguitarpro.py index.html ./

# Attribution des droits sur le dossier de travail et les certificats si nécessaire
RUN chown -R appuser:appgroup /app

# Exécution sous l'utilisateur non-root
USER appuser

# Exposition du port (Render mappe automatiquement $PORT)
EXPOSE 10000

# Lancement de l'application avec le serveur WSGI Gunicorn
CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT:-10000} --workers 2 --threads 4 --timeout 60 --access-logfile - --error-logfile - app:app"]