# ============================================================
# Backend/main.py
# ============================================================
# RÔLE : Point d'entrée FastAPI — endpoints de recommandation
#        (pièces manquantes, tenues, analyse de garde-robe,
#        suppression de fond, analyse de tenue par photo).
#
# DESCRIPTION :
#   Backend FastAPI complémentaire au serveur Node.js (server.js).
#   Authentifie les utilisateurs via auth.get_current_user()
#   (Bearer token, même session que Node, lue dans Frontend/db.json),
#   construit une GarderobeSchema à partir des données utilisateur
#   et délègue les calculs aux modules services/ (pieces_manquantes,
#   outfit_model) et agent/ (analyse_tenue, conseil).
#
#   Lancer : uvicorn main:app --reload --port 8000
#
#   ATTENTION (signalé, non corrigé) :
#   - /image/remove-bg, /recommander/pieces-manquantes et
#     /analyse/garderobe n'ont pas de try/except -> une erreur
#     interne renvoie un 500 FastAPI générique au lieu d'une
#     HTTPException explicite.
#   - /recommander/tenues, /analyse/garderobe et /api/agent/conseil
#     ne semblent appelés par aucune page du Frontend (le frontend
#     utilise /api/agent/conseil du serveur Node, pas celui-ci).
#
# FONCTIONS / ENDPOINTS PRINCIPAUX :
#   - _saison_actuelle()                 : déduit la saison courante du mois
#   - _user_to_garderobe(user)            : convertit les données utilisateur en GarderobeSchema + préférences
#   - POST /image/remove-bg               : supprime le fond d'une image (rembg)
#   - GET  /                              : ping / liste des endpoints
#   - GET  /recommander/pieces-manquantes : pièces manquantes + score de complétude
#   - GET  /recommander/tenues            : génère des propositions de tenues
#   - GET  /analyse/garderobe             : statistiques de la garde-robe
#   - POST /api/analyse-tenue             : analyse une photo de tenue via LLM vision
#   - POST /api/agent/conseil             : compose une tenue via l'agent de conseil
#   - _famille_couleur_local(couleur)     : classe une couleur par famille (pour le score de diversité)
#
# DÉPENDANCES :
#   - fastapi, pydantic
#   - auth (get_current_user), schemas (Garderobe*, Recommandation*, Tenue*)
#   - services.pieces_manquantes (analyser_pieces_manquantes)
#   - services.outfit_model (recommander_tenues, COULEURS_*)
#   - agent.analyse_tenue (analyser_tenue), agent.conseil (conseiller)
#
# APPELS ENTRANTS :
#   - Frontend (page_apres_connection.html -> /recommander/pieces-manquantes,
#     page_categorie_garderobe.html -> /api/analyse-tenue), en appel direct
#     localhost:8000 (voir audit frontend)
#
# APPELS SORTANTS :
#   - Frontend/db.json (lecture utilisateurs/garde-robe)
#   - rembg.remove(), agent.analyse_tenue.analyser_tenue() (Groq), agent.conseil.conseiller() (Groq)
# ============================================================

import json
import os
import sys
import tempfile
from pathlib import Path

from fastapi import FastAPI, Depends, HTTPException, UploadFile, File
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel
from datetime import date
import io

# Expose project root so agent/ package is importable
sys.path.insert(0, str(Path(__file__).parent.parent))
from agent.analyse_tenue import analyser_tenue
from agent.conseil import conseiller

from auth import get_current_user
from schemas import (
    RecommandationRequest, RecommandationResponse,
    TenueRequest, TenueResponse,
    GarderobeSchema, VetementSchema,
)
from services.pieces_manquantes import analyser_pieces_manquantes
from services.outfit_model import recommander_tenues

app = FastAPI(
    title="SmartWear API",
    description="Backend de recommandation mode — pièces manquantes & tenues personnalisées",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000", "http://127.0.0.1:3000",
        "http://localhost:8000", "http://127.0.0.1:8000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Helpers ───────────────────────────────────────────────────────────
# Déduit la saison courante (Printemps/Été/Automne/Hiver) à partir du mois actuel.
def _saison_actuelle() -> str:
    m = date.today().month
    if m in (3, 4, 5):   return "Printemps"
    if m in (6, 7, 8):   return "Été"
    if m in (9, 10, 11): return "Automne"
    return "Hiver"

def _user_to_garderobe(user: dict) -> tuple[GarderobeSchema, list, list, str]:
    """Extrait la garde-robe et les préférences depuis les données utilisateur."""
    data       = user.get("data", {})
    wardrobe   = data.get("wardrobe", {})
    user_info  = data.get("user", {})
    styles     = list(set(user_info.get("styles", [])))
    contextes  = user_info.get("contextes", [])
    genre      = user_info.get("genre", "Femme")

    # Convertit une liste brute d'items db.json en liste de VetementSchema, étiquetée avec sa catégorie.
    def to_items(cat_list, cat_name):
        items = []
        for item in (cat_list or []):
            items.append(VetementSchema(
                id=item.get("id"),
                nom=item.get("nom") or item.get("name") or "Article",
                marque=item.get("marque"),
                couleur=item.get("couleur"),
                taille=item.get("taille"),
                portes=item.get("portes", 0),
                saisons=item.get("saisons", []),
                categorie=cat_name,
            ))
        return items

    garderobe = GarderobeSchema(
        haut=        to_items(wardrobe.get("haut"),        "haut"),
        bas=         to_items(wardrobe.get("bas"),         "bas"),
        manteau=     to_items(wardrobe.get("manteau"),     "manteau"),
        ensemble=    to_items(wardrobe.get("ensemble"),    "ensemble"),
        chaussures=  to_items(wardrobe.get("chaussures"),  "chaussures"),
        accessoires= to_items(wardrobe.get("accessoires"), "accessoires"),
    )
    return garderobe, styles, contextes, genre

# ── Routes ────────────────────────────────────────────────────────────

@app.post("/image/remove-bg")
async def remove_background(file: UploadFile = File(...)):
    """
    Supprime le fond d'une image et retourne un PNG avec fond transparent.
    """
    from rembg import remove
    contents = await file.read()
    output = remove(contents)
    return Response(content=output, media_type="image/png")

# Endpoint racine : ping de santé + liste des endpoints de recommandation disponibles.
@app.get("/")
def root():
    return {
        "app": "SmartWear API",
        "version": "1.0.0",
        "endpoints": [
            "/recommander/pieces-manquantes",
            "/recommander/tenues",
            "/analyse/garderobe",
        ]
    }

@app.get("/recommander/pieces-manquantes", response_model=RecommandationResponse)
def pieces_manquantes(current_user: dict = Depends(get_current_user)):
    """
    Analyse la garde-robe de l'utilisateur connecté et retourne
    les pièces manquantes selon ses styles et contextes déclarés.
    """
    garderobe, styles, contextes, genre = _user_to_garderobe(current_user)

    manquantes, score = analyser_pieces_manquantes(
        garderobe=garderobe,
        styles=styles,
        contextes=contextes,
        genre=genre,
        saison=_saison_actuelle(),
    )

    if score == 100:
        message = "Votre garde-robe est complète ! Toutes les catégories sont représentées."
    elif score >= 70:
        message = f"Votre garde-robe est bien fournie ({score}%). Quelques pièces peuvent l'enrichir."
    elif score >= 40:
        message = f"Votre garde-robe est en cours de constitution ({score}%). Voici les priorités."
    else:
        message = f"Votre garde-robe ({score}%) nécessite quelques essentiels pour composer des tenues complètes."

    return RecommandationResponse(
        pieces_manquantes=manquantes,
        score_completude=score,
        message=message,
    )

@app.get("/recommander/tenues", response_model=TenueResponse)
def recommander(
    nb: int = 1,
    current_user: dict = Depends(get_current_user),
):
    """
    Génère des propositions de tenues cohérentes basées sur la garde-robe
    de l'utilisateur, ses styles préférés et ses contextes d'utilisation.

    - nb=1  → gratuit
    - nb=3  → premium
    - nb=5+ → famille (illimité en pratique)
    """
    garderobe, styles, contextes, genre = _user_to_garderobe(current_user)

    tenues = recommander_tenues(
        garderobe=garderobe,
        styles=styles,
        contextes=contextes,
        nb=min(nb, 20),  # Sécurité : max 20 par requête
    )

    if not tenues:
        raise HTTPException(
            status_code=422,
            detail="Impossible de composer une tenue — ajoutez au moins 1 haut/ensemble, 1 bas et 1 paire de chaussures."
        )

    return TenueResponse(tenues=tenues)

@app.get("/analyse/garderobe")
def analyse_garderobe(current_user: dict = Depends(get_current_user)):
    """
    Analyse complète de la garde-robe : stats, couleurs dominantes,
    articles les plus portés, répartition par catégorie.
    """
    garderobe, styles, contextes, genre = _user_to_garderobe(current_user)

    # Calcule les statistiques d'une catégorie : total, jamais portés, top 3 des plus portés.
    def stats_cat(items):
        return {
            "total": len(items),
            "jamais_portes": sum(1 for i in items if not i.portes or i.portes == 0),
            "plus_portes": sorted(
                [{"nom": i.nom, "portes": i.portes or 0} for i in items],
                key=lambda x: x["portes"], reverse=True
            )[:3],
        }

    all_items = (
        garderobe.haut + garderobe.bas + garderobe.manteau +
        garderobe.ensemble + garderobe.chaussures + garderobe.accessoires
    )

    # Couleurs dominantes
    from collections import Counter
    couleurs = [i.couleur for i in all_items if i.couleur]
    couleurs_top = [c for c, _ in Counter(couleurs).most_common(5)]

    # Score de diversité des couleurs (0-100)
    familles = [_famille_couleur_local(i.couleur or "") for i in all_items]
    diversite = len(set(familles)) / 5 * 100 if familles else 0

    return {
        "utilisateur": {
            "prenom":    current_user["prenom"],
            "styles":    styles,
            "contextes": contextes,
            "genre":     genre,
            "saison":    _saison_actuelle(),
        },
        "stats": {
            "total":        len(all_items),
            "haut":         stats_cat(garderobe.haut),
            "bas":          stats_cat(garderobe.bas),
            "manteau":      stats_cat(garderobe.manteau),
            "ensemble":     stats_cat(garderobe.ensemble),
            "chaussures":   stats_cat(garderobe.chaussures),
            "accessoires":  stats_cat(garderobe.accessoires),
        },
        "couleurs_dominantes": couleurs_top,
        "score_diversite_couleurs": round(diversite),
        "articles_jamais_portes": sum(
            1 for i in all_items if not i.portes or i.portes == 0
        ),
    }

# Payload de POST /api/agent/conseil : identifiant utilisateur + demande en langage libre.
class ConseilRequest(BaseModel):
    userId: str
    demande: str


@app.post("/api/analyse-tenue")
async def analyse_tenue_endpoint(file: UploadFile = File(...)):
    """
    Analyse une photo de tenue complète via LLM vision.
    Retourne {vetements, style_global, occasions}.
    """
    suffix = Path(file.filename or "tenue.jpg").suffix or ".jpg"
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name
        result = await run_in_threadpool(analyser_tenue, tmp_path)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Erreur analyse tenue : {e}")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)
    return result


@app.post("/api/agent/conseil")
async def agent_conseil(req: ConseilRequest):
    """
    Compose une tenue à partir de la garde-robe et du profil de l'utilisateur.
    """
    db_path = Path(__file__).parent.parent / "Frontend" / "db.json"
    try:
        with open(db_path, encoding="utf-8") as f:
            db = json.load(f)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Base de données introuvable")

    wardrobe = db.get("wardrobe", {}).get(req.userId)
    if wardrobe is None:
        raise HTTPException(status_code=404, detail=f"Garde-robe introuvable pour l'utilisateur {req.userId}")

    profil = next((u for u in db.get("users", []) if u.get("id") == req.userId), {})

    try:
        result = await run_in_threadpool(conseiller, wardrobe, profil, req.demande)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Erreur agent conseil : {e}")

    return result


# Classe une couleur par famille (neutre/chaude/froide/pastel/autre), réimport local pour le score de diversité.
def _famille_couleur_local(couleur: str) -> str:
    from services.outfit_model import (
        COULEURS_NEUTRES, COULEURS_CHAUDES, COULEURS_FROIDES, COULEURS_PASTEL
    )
    c = couleur.lower()
    for n in COULEURS_NEUTRES:
        if n in c: return "neutre"
    for n in COULEURS_CHAUDES:
        if n in c: return "chaude"
    for n in COULEURS_FROIDES:
        if n in c: return "froide"
    for n in COULEURS_PASTEL:
        if n in c: return "pastel"
    return "autre"
