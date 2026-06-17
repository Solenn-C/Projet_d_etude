"""
Analyse une image de vêtement via LLM vision (Groq + Llama 4 Scout).
Retourne la couleur, les saisons et la marque (si visible).

Usage :
    from agent.analyse_image import analyser_image

    result = analyser_image("chemin/vers/image.jpg")
    result = analyser_image("https://example.com/image.jpg")
"""

import base64
import json
import os
import re
from pathlib import Path

import requests
from groq import Groq
from dotenv import load_dotenv

# Cherche .env dans le dossier parent si pas trouvé localement
load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

SAISONS_VALIDES = ["Printemps", "Été", "Automne", "Hiver"]

PROMPT_TEMPLATE = """Analyse cette image et réponds en JSON uniquement, sans markdown.

{focus}

Extrais UNIQUEMENT pour ce vêtement spécifique :
1. couleur : sa couleur principale (en français, ex: "Bleu marine", "Blanc cassé", "Rouge bordeaux")
2. couleurs_secondaires : ses autres couleurs visibles (peut être vide)
3. saisons : liste des saisons adaptées parmi exactement ces valeurs : "Printemps", "Été", "Automne", "Hiver"
   - Été : tissus légers, sans manches, shorts, robes légères
   - Printemps : léger mais couvert, couleurs vives
   - Automne : couches, matières plus épaisses
   - Hiver : manteaux, pulls épais, matières chaudes
4. marque : nom de la marque si un logo ou une étiquette est clairement visible, sinon null
5. confidence_marque : "haute", "moyenne" ou "faible" selon la lisibilité du logo

Réponds uniquement avec ce JSON :
{{
  "couleur": "...",
  "couleurs_secondaires": [],
  "saisons": [],
  "marque": null,
  "confidence_marque": "faible"
}}"""


def _image_to_base64(source: str) -> tuple[str, str]:
    """Convertit une image (chemin local ou URL) en base64. Retourne (base64, media_type)."""
    if source.startswith("http://") or source.startswith("https://"):
        resp = requests.get(source, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        data = resp.content
        content_type = resp.headers.get("Content-Type", "image/jpeg").split(";")[0]
    else:
        path = Path(source)
        data = path.read_bytes()
        ext = path.suffix.lower()
        content_type = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
        }.get(ext, "image/jpeg")

    return base64.b64encode(data).decode("utf-8"), content_type


def analyser_image(source: str, type_vetement: str | None = None) -> dict:
    """
    Analyse un vêtement sur une image.

    Args:
        source          : chemin local (str/Path) ou URL de l'image
        type_vetement   : type prédit par le CNN (ex: "Jean", "Robe") pour guider le LLM

    Returns:
        dict avec clés : couleur, couleurs_secondaires, saisons, marque, confidence_marque
    """
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY manquant dans .env")

    client = Groq(api_key=api_key)

    image_b64, media_type = _image_to_base64(str(source))

    if type_vetement:
        focus = f"IMPORTANT : concentre-toi UNIQUEMENT sur le/la {type_vetement} visible sur l'image. Ignore tous les autres vêtements portés par le modèle (hauts, accessoires, chaussures, etc.)."
    else:
        focus = "Concentre-toi sur le vêtement principal mis en avant sur la photo (généralement au centre ou le plus visible)."

    prompt = PROMPT_TEMPLATE.format(focus=focus)

    response = client.chat.completions.create(
        model="meta-llama/llama-4-scout-17b-16e-instruct",
        max_tokens=300,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{media_type};base64,{image_b64}"
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    )

    raw = response.choices[0].message.content.strip()
    raw = re.sub(r"^```json\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    result = json.loads(raw)

    # Filtrer les saisons invalides
    result["saisons"] = [s for s in result.get("saisons", []) if s in SAISONS_VALIDES]

    # Ignorer la marque si la confidence est faible
    if result.get("confidence_marque") == "faible":
        result["marque"] = None

    return result
