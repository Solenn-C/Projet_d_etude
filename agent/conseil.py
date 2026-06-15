# ============================================================
# agent/conseil.py
# ============================================================
# RÔLE : Agent de conseil vestimentaire — compose une tenue
#        adaptée à une demande à partir de la garde-robe et du
#        profil d'un utilisateur.
#
# DESCRIPTION :
#   Construit un prompt décrivant la garde-robe (db.json), le
#   profil (styles, contextes, genre) et les hauts portés
#   récemment, puis l'envoie à Groq (llama-3.3-70b-versatile).
#   La tenue renvoyée par le LLM (noms de pièces) est ensuite
#   "enrichie" : chaque nom est retrouvé dans la garde-robe
#   (correspondance exacte normalisée, puis fuzzy matching) pour
#   renvoyer les items complets.
#
#   Usage depuis FastAPI :
#       from agent.conseil import conseiller
#       result = conseiller(wardrobe=wardrobe_dict, profil=profil_dict, demande="soirée au restaurant")
#
# FONCTIONS / ENDPOINTS PRINCIPAUX :
#   - _format_wardrobe(wardrobe)        : formate la garde-robe en texte lisible pour le prompt
#   - _build_prompt(...)                 : construit le prompt complet envoyé à Groq
#   - _hauts_recents(wardrobe, n)        : renvoie les n hauts les plus récemment portés
#   - _normalize(s)                      : normalise une chaîne (minuscule, sans accents) pour le matching
#   - _find_item(wardrobe, nom)          : retrouve un item de la garde-robe par son nom (exact puis fuzzy)
#   - conseiller(...)                    : appelle Groq et renvoie {tenue, style_tenue, conseil, occasion}
#
# DÉPENDANCES :
#   - groq (Groq), dotenv (.env -> GROQ_API_KEY), difflib, unicodedata
#
# APPELS ENTRANTS :
#   - scripts/conseil_tenue.py (wrapper CLI appelé par server.js)
#   - Backend/main.py (route /api/agent/conseil — endpoint non utilisé par le frontend, voir audit)
#
# APPELS SORTANTS :
#   - API Groq (chat.completions, modèle llama-3.3-70b-versatile)
# ============================================================

import difflib
import json
import os
import re
import sys
import unicodedata

from groq import Groq
from dotenv import load_dotenv

load_dotenv()

CATEGORY_LABELS = {
    "ensemble": "Robes / Combinaisons",
    "haut":     "Hauts (t-shirts, blouses, tops...)",
    "bas":      "Bas (jeans, pantalons, jupes...)",
    "manteau":  "Vestes / Manteaux",
    "chaussures": "Chaussures",
    "accessoires": "Accessoires",
}

STYLES_DESCRIPTIONS = {
    "Casual chic":  "décontracté mais soigné, touche élégante au quotidien",
    "Minimaliste":  "basiques épurés, couleurs neutres, lignes simples",
    "Classique":    "intemporel, tailoring, élégance sobre",
    "Streetwear":   "urban, oversized, hoodies, sneakers",
    "Bohème":       "fluidité, imprimés naturels, superpositions",
    "Romantique":   "dentelles, fleurs, couleurs douces, féminité",
    "Élégant":      "sophistiqué, occasions formelles",
    "Sportswear":   "fonctionnel, confort, mouvement",
    "Vintage":      "inspirations rétro, coupes d'époque",
    "Smart casual": "entre formel et décontracté, bureau ou dîner",
    "Preppy":       "campus américain, couleurs vives, coupes nettes",
    "Avant-garde":  "créatif, audacieux, formes inattendues",
}


def _format_wardrobe(wardrobe: dict) -> str:
    """Formate la garde-robe en texte lisible pour le prompt."""
    lines = []
    for category, items in wardrobe.items():
        if not items:
            continue
        label = CATEGORY_LABELS.get(category, category.capitalize())
        lines.append(f"\n{label} :")
        for item in items:
            nom     = item.get("nom", "?")
            couleur = item.get("couleur", "couleur inconnue")
            marque  = item.get("marque", "")
            saisons = item.get("saisons", [])
            saisons_clean = [s for s in saisons if isinstance(s, str)]
            line = f"  - {nom} ({couleur})"
            if marque:
                line += f" — {marque}"
            if saisons_clean:
                line += f" [saisons: {', '.join(saisons_clean)}]"
            lines.append(line)
    return "\n".join(lines) if lines else "Garde-robe vide."


# Construit le prompt complet (profil, garde-robe, hauts récents, demande, consignes) envoyé à Groq.
def _build_prompt(wardrobe: dict, profil: dict, demande: str, recent_items: list[str]) -> str:
    prenom   = profil.get("prenom", "l'utilisateur")
    genre    = profil.get("genre", "")
    styles   = profil.get("styles", [])
    contextes = profil.get("contextes", [])

    styles_unique = list(dict.fromkeys(styles))
    styles_desc = ", ".join(
        f"{s} ({STYLES_DESCRIPTIONS.get(s, '')})" for s in styles_unique
    )

    wardrobe_text = _format_wardrobe(wardrobe)

    recents_text = "\n".join(f"  - {nom}" for nom in recent_items) if recent_items else "  (aucun)"

    return f"""Tu es un assistant mode expert. Tu conseilles {prenom} pour composer une tenue.

PROFIL :
- Genre : {genre}
- Styles préférés : {styles_desc}
- Contextes habituels : {', '.join(contextes)}

GARDE-ROBE DISPONIBLE :
{wardrobe_text}

HAUTS PORTÉS RÉCEMMENT (du plus récent au plus ancien) :
{recents_text}

DEMANDE : {demande}

CONSIGNES :
- Compose une tenue uniquement avec les pièces disponibles dans la garde-robe
- Respecte les styles préférés de l'utilisateur si possible
- Prends en compte la saison et l'occasion
- RÈGLE OBLIGATOIRE : la tenue DOIT contenir au minimum un haut ET un bas ET des chaussures, OU un ensemble ET des chaussures. Si aucune chaussure n'est disponible dans la garde-robe, choisis quand même la tenue haut+bas (ou ensemble) la plus cohérente et laisse "chaussures" à null. Ne retourne JAMAIS une tenue avec seulement une pièce (ex: robe seule sans chaussures)
- Si la température est inférieure à 15°C, inclure un manteau si la garde-robe en contient un adapté à la saison
- Privilégie la variété : évite de reproposer un haut listé dans "HAUTS PORTÉS RÉCEMMENT" sauf si aucune alternative pertinente n'existe pour la météo/le contexte
- Si plusieurs hauts conviennent à la météo et au contexte, choisis celui le moins récemment porté (en bas de la liste "HAUTS PORTÉS RÉCEMMENT", ou absent de cette liste)
- Les accessoires sont optionnels : ne les évoque dans le conseil que s'ils sont vraiment pertinents pour l'occasion
- Explique brièvement pourquoi chaque pièce a été choisie

RÉPONSE (JSON uniquement, sans markdown) :
{{
  "tenue": {{
    "ensemble": "nom de la pièce ou null",
    "haut": "nom de la pièce ou null",
    "bas": "nom de la pièce ou null",
    "manteau": "nom de la pièce ou null",
    "chaussures": "nom de la pièce ou null"
  }},
  "style_tenue": "nom du style correspondant",
  "conseil": "2-3 phrases expliquant les choix et comment porter la tenue",
  "occasion": "reformulation courte de l'occasion"
}}"""


def _hauts_recents(wardrobe: dict, n: int = 4) -> list[str]:
    """Retourne les noms des n hauts les plus récemment portés (par dernierPort), du plus récent au plus ancien."""
    hauts = [h for h in wardrobe.get("haut", []) if h.get("dernierPort")]
    hauts.sort(key=lambda h: h["dernierPort"], reverse=True)
    return [h.get("nom", "?") for h in hauts[:n]]


# Normalise une chaîne (minuscules, sans accents, espaces superflus retirés) pour le matching de noms.
def _normalize(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii").lower().strip()


def _find_item(wardrobe: dict, nom: str) -> dict | None:
    """Retrouve un item de la garde-robe par son nom (exact normalisé puis fuzzy)."""
    print(f"[DEBUG garde-robe] {[item.get('nom','?') for items in wardrobe.values() for item in items]}",
          file=sys.stderr, flush=True)
    if not nom or nom == "null":
        result = None
        print(f"[DEBUG _find_item] brut: '{nom}' → nettoyé: '' → trouvé: {result is not None}",
              file=sys.stderr, flush=True)
        return result

    # Nettoyage : retire " — Marque" puis "(couleur)" avant le matching
    nom_nettoye = re.sub(r'\s*\([^)]*\)', '', nom.split(' — ')[0]).strip()
    nom_n = _normalize(nom_nettoye)

    for items in wardrobe.values():
        for item in items:
            if _normalize(item.get("nom", "")) == nom_n:
                result = item
                print(f"[DEBUG _find_item] brut: '{nom}' → nettoyé: '{nom_nettoye}' → trouvé: {result is not None}",
                      file=sys.stderr, flush=True)
                return result
    best_item, best_ratio = None, 0.0
    for items in wardrobe.values():
        for item in items:
            ratio = difflib.SequenceMatcher(None, _normalize(item.get("nom", "")), nom_n).ratio()
            if ratio > best_ratio:
                best_ratio, best_item = ratio, item
    result = best_item if best_ratio >= 0.6 else None
    print(f"[DEBUG _find_item] brut: '{nom}' → nettoyé: '{nom_nettoye}' → trouvé: {result is not None}",
          file=sys.stderr, flush=True)
    return result


def conseiller(wardrobe: dict, profil: dict, demande: str, recent_items: list[str] | None = None, temperature: float = 0.7) -> dict:
    """
    Compose une tenue à partir de la garde-robe et du profil.

    Args:
        wardrobe     : dict issu de db.json["wardrobe"][userId]
        profil       : dict issu de db.json["profiles"] (le profil principal)
        demande      : str, ex. "j'ai une soirée au restaurant ce soir, tenue chic"
        recent_items : noms des hauts portés récemment (du plus récent au plus ancien),
                        pour favoriser la variété. Si None, déduit de wardrobe["haut"]
                        via le champ "dernierPort".
        temperature  : température de l'appel Groq (diversité des réponses)

    Returns:
        dict avec clés : tenue (items complets), style_tenue, conseil, occasion
    """
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY manquant dans .env")

    client = Groq(api_key=api_key)

    if recent_items is None:
        recent_items = _hauts_recents(wardrobe)

    prompt = _build_prompt(wardrobe, profil, demande, recent_items)

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        max_tokens=800,
        temperature=temperature,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.choices[0].message.content.strip()

    # Nettoyer les backticks éventuels renvoyés par le LLM
    raw = re.sub(r"^```json\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    result = json.loads(raw)

    # Enrichir les items de la tenue avec les données complètes
    tenue_enrichie = {}
    for key, nom in result.get("tenue", {}).items():
        if not nom or nom == "None" or nom.lower() == "none":
            tenue_enrichie[key] = None
            continue
        item = _find_item(wardrobe, nom)
        tenue_enrichie[key] = item if item else None

    result["tenue"] = tenue_enrichie
    return result
