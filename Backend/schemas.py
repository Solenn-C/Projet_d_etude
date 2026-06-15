# ============================================================
# Backend/schemas.py
# ============================================================
# RÔLE : Modèles Pydantic (requêtes/réponses) utilisés par les
#        endpoints de recommandation de Backend/main.py.
#
# DESCRIPTION :
#   Définit la structure d'une garde-robe (VetementSchema,
#   GarderobeSchema), des requêtes envoyées par le frontend
#   (RecommandationRequest, TenueRequest) et des réponses
#   renvoyées par l'API (RecommandationResponse, TenueResponse,
#   PieceManquante, Tenue, PieceTenue). Ces modèles servent de
#   validation automatique et de documentation OpenAPI pour
#   FastAPI.
#
# FONCTIONS / ENDPOINTS PRINCIPAUX :
#   - VetementSchema / GarderobeSchema     : structure d'un vêtement / d'une garde-robe
#   - RecommandationRequest / TenueRequest  : payloads entrants
#   - RecommandationResponse / TenueResponse / PieceManquante / Tenue / PieceTenue : payloads sortants
#
# DÉPENDANCES :
#   - pydantic
#
# APPELS ENTRANTS :
#   - Backend/main.py (response_model=..., paramètres des endpoints)
#
# APPELS SORTANTS :
#   - (aucun)
# ============================================================

from pydantic import BaseModel
from typing import List, Optional

# ── Vêtement ─────────────────────────────────
class VetementSchema(BaseModel):
    id: Optional[int] = None
    nom: str
    marque: Optional[str] = None
    couleur: Optional[str] = None
    taille: Optional[str] = None
    portes: Optional[int] = 0
    saisons: Optional[List[str]] = []
    categorie: Optional[str] = None   # haut / bas / manteau / ...

class GarderobeSchema(BaseModel):
    haut: List[VetementSchema] = []
    bas: List[VetementSchema] = []
    manteau: List[VetementSchema] = []
    ensemble: List[VetementSchema] = []
    chaussures: List[VetementSchema] = []
    accessoires: List[VetementSchema] = []

# ── Requêtes ─────────────────────────────────
class RecommandationRequest(BaseModel):
    user_id: str
    styles: List[str] = []          # ["Bohème", "Romantique", "Vintage"]
    contextes: List[str] = []       # ["quotidien", "bureau", "soiree"]
    genre: Optional[str] = "Femme"  # Femme / Homme
    saison: Optional[str] = None    # Auto-détectée si absent
    garderobe: GarderobeSchema

class TenueRequest(BaseModel):
    user_id: str
    styles: List[str] = []
    contextes: List[str] = []
    genre: Optional[str] = "Femme"
    garderobe: GarderobeSchema
    nb_propositions: Optional[int] = 1  # 1 / 3 / illimité

# ── Réponses ─────────────────────────────────
class PieceManquante(BaseModel):
    categorie: str          # "Haut", "Bas", "Chaussures"...
    raison: str             # Pourquoi c'est manquant
    priorite: str           # "haute" / "moyenne" / "faible"
    suggestions: List[str]  # Types de pièces à ajouter

class RecommandationResponse(BaseModel):
    pieces_manquantes: List[PieceManquante]
    score_completude: int   # 0-100
    message: str

class PieceTenue(BaseModel):
    nom: str
    categorie: str
    couleur: Optional[str] = None

class Tenue(BaseModel):
    pieces: List[PieceTenue]
    conseil: str
    style_dominant: str
    contexte: str

class TenueResponse(BaseModel):
    tenues: List[Tenue]
