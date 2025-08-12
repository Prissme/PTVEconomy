# Base image Python officielle
FROM python:3.11-slim

# Installer les dépendances système nécessaires
RUN apt-get update && apt-get install -y \
    build-essential \
    libffi-dev \
    libssl-dev \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Copier les fichiers requirements.txt et installer les packages Python
COPY requirements.txt /app/requirements.txt
WORKDIR /app
RUN pip install --upgrade pip setuptools wheel
RUN pip install -r requirements.txt

# Copier le code source
COPY . /app

# Commande pour lancer le bot
CMD ["python", "bot.py"]