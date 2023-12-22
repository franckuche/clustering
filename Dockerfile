# Utiliser une image de base Python
FROM python:3.8

# Définir le répertoire de travail
WORKDIR /app

# Copier les fichiers de dépendances et installer les dépendances
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copier le reste des fichiers de votre application
COPY . .

# Exposer le port sur lequel votre application s'exécute
EXPOSE 8000

# Commande pour lancer l'application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]