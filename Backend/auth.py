# ============================================================
# Backend/auth.py
# ============================================================
# RÔLE : Authentification FastAPI par Bearer token, partagée avec
#        le serveur Node (server.js) via Frontend/db.json.
#
# DESCRIPTION :
#   Lit Frontend/db.json (la même base que server.js) pour
#   résoudre un token Bearer en utilisateur courant. Ne crée ni
#   ne modifie jamais de session — c'est server.js (route
#   /api/auth/login) qui écrit db.sessions. Ce module se contente
#   de vérifier le token et de renvoyer l'utilisateur + sa
#   garde-robe à get_current_user(), utilisé comme dépendance
#   FastAPI (Depends) sur les endpoints protégés de main.py.
#
# FONCTIONS / ENDPOINTS PRINCIPAUX :
#   - read_db()           : charge Frontend/db.json (dict vide par défaut si erreur)
#   - get_current_user()  : valide le Bearer token et retourne l'utilisateur + sa garde-robe
#
# DÉPENDANCES :
#   - fastapi (HTTPException, Security, HTTPBearer, HTTPAuthorizationCredentials)
#   - Frontend/db.json (sessions, users, wardrobe)
#
# APPELS ENTRANTS :
#   - Backend/main.py (Depends(get_current_user) sur les endpoints protégés)
#
# APPELS SORTANTS :
#   - (aucun — lecture fichier uniquement)
# ============================================================

import json
from pathlib import Path
from fastapi import HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

BASE_DIR = Path(__file__).parent.parent
DB_PATH  = BASE_DIR / "Frontend" / "db.json"

security = HTTPBearer()

# Charge Frontend/db.json ; renvoie une base vide si le fichier est absent ou invalide.
def read_db() -> dict:
    try:
        with open(DB_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"users": [], "sessions": {}, "wardrobe": {}}

def get_current_user(credentials: HTTPAuthorizationCredentials = Security(security)) -> dict:
    """
    Valide le Bearer token et retourne l'utilisateur + sa garde-robe.
    Lit tout depuis Frontend/db.json (même source que le serveur Node.js).
    """
    token = credentials.credentials
    db    = read_db()

    sessions = db.get("sessions", {})
    # Support format dict { token: userId }
    if isinstance(sessions, dict):
        user_id = sessions.get(token)
    else:
        # Format array legacy [{ token, userId, expiresAt }]
        session = next((s for s in sessions if s.get("token") == token), None)
        user_id = session.get("userId") if session else None

    if not user_id:
        raise HTTPException(status_code=401, detail="Token invalide ou expiré")

    db_user = next((u for u in db.get("users", []) if u["id"] == user_id), None)
    if not db_user:
        raise HTTPException(status_code=401, detail="Utilisateur introuvable")

    # Garde-robe stockée dans db.wardrobe[userId]
    wardrobe = db.get("wardrobe", {}).get(user_id, {})

    return {
        "id":       user_id,
        "prenom":   db_user.get("prenom", ""),
        "nom":      db_user.get("nom", ""),
        "email":    db_user.get("email", ""),
        "data": {
            "user":     db_user,
            "wardrobe": wardrobe,
        }
    }
