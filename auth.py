from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import secrets

# Utilisateurs définis (exemple simplifié)
users = {
    "SeoenThong": "Francklebest",
    "Franck": "Franckuche",
}

security = HTTPBasic()

def authenticate_user(credentials: HTTPBasicCredentials = Depends(security)):
    username = credentials.username
    password = credentials.password

    if username in users and secrets.compare_digest(password, users[username]):
        return username
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Informations d'identification incorrectes",
        headers={"WWW-Authenticate": "Basic"},
    )