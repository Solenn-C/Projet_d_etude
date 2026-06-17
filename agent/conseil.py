"""
Agent de conseil vestimentaire.

Prend la garde-robe et le profil d'un utilisateur (depuis db.json)
et compose une tenue adaptée à la demande.

Usage depuis FastAPI :
    from agent.conseil import conseiller

    result = await conseiller(wardrobe=wardrobe_dict, profil=profil_dict, demande="soirée au restaurant")
"""

import json
import os
import re

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
            saisons_clean = [s.encode("latin-1").decode("utf-8", errors="replace")
                             if isinstance(s, str) else s for s in saisons]
            line = f"  - {nom} ({couleur})"
            if marque:
                line += f" — {marque}"
            if saisons_clean:
                line += f" [saisons: {', '.join(saisons_clean)}]"
            lines.append(line)
    return "\n".join(lines) if lines else "Garde-robe vide."


def _build_prompt(wardrobe: dict, profil: dict, demande: str) -> str:
    prenom   = profil.get("prenom", "l'utilisateur")
    genre    = profil.get("genre", "")
    styles   = profil.get("styles", [])
    contextes_raw = profil.get("contextes", [])
    # Normalisation vers les 4 occasions du site
    contexte_map = {
        "quotidien": "vie quotidienne",
        "bureau": "professionnel",
        "sport": "sport & loisirs",
        "soiree": "soirée & évènement",
    }
    contextes = [contexte_map.get(c, c) for c in contextes_raw]

    styles_unique = list(dict.fromkeys(styles))
    styles_desc = ", ".join(
        f"{s} ({STYLES_DESCRIPTIONS.get(s, '')})" for s in styles_unique
    )

    wardrobe_text = _format_wardrobe(wardrobe)

    return f"""Tu es un assistant mode expert. Tu conseilles {prenom} pour composer une tenue.

PROFIL :
- Genre : {genre}
- Styles préférés : {styles_desc}
- Contextes habituels : {', '.join(contextes)}

GARDE-ROBE DISPONIBLE :
{wardrobe_text}

DEMANDE : {demande}

CONSIGNES :
- Compose une tenue uniquement avec les pièces disponibles dans la garde-robe
- Respecte les styles préférés de l'utilisateur si possible
- Prends en compte la saison et l'occasion
- Pour une tenue complète : choisis soit un ensemble (robe/combinaison) seul + chaussures, soit haut + bas + chaussures
- Tu peux ajouter une veste/manteau si pertinent
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


def _find_item(wardrobe: dict, nom: str) -> dict | None:
    """Retrouve un item de la garde-robe par son nom."""
    if not nom or nom == "null":
        return None
    for items in wardrobe.values():
        for item in items:
            if item.get("nom", "").lower() == nom.lower():
                return item
    return None


def conseiller(wardrobe: dict, profil: dict, demande: str) -> dict:
    """
    Compose une tenue à partir de la garde-robe et du profil.

    Args:
        wardrobe : dict issu de db.json["wardrobe"][userId]
        profil   : dict issu de db.json["profiles"] (le profil principal)
        demande  : str, ex. "j'ai une soirée au restaurant ce soir, tenue chic"

    Returns:
        dict avec clés : tenue (items complets), style_tenue, conseil, occasion
    """
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY manquant dans .env")

    client = Groq(api_key=api_key)
    prompt = _build_prompt(wardrobe, profil, demande)

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        max_tokens=800,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.choices[0].message.content.strip()

    # Nettoyer le JSON si Claude a ajouté des backticks
    raw = re.sub(r"^```json\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    result = json.loads(raw)

    # Enrichir les items de la tenue avec les données complètes
    tenue_enrichie = {}
    for key, nom in result.get("tenue", {}).items():
        item = _find_item(wardrobe, nom)
        tenue_enrichie[key] = item if item else None

    result["tenue"] = tenue_enrichie
    return result
