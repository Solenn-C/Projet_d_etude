"""
Analyse une photo de tenue complète via LLM vision (Groq + Llama 4 Scout).
Identifie tous les vêtements visibles et leurs caractéristiques.

Usage :
    from agent.analyse_tenue import analyser_tenue

    result = analyser_tenue("chemin/vers/photo.jpg")
"""

import base64
import json
import os
import re
from pathlib import Path

import requests
from groq import Groq
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

TYPES_VALIDES = [
    "T-shirt", "Chemise", "Pull", "Sweat", "Top", "Polo",
    "Jean", "Pantalon", "Short", "Jupe", "Jogging",
    "Robe", "Combinaison", "Ensemble",
    "Veste", "Manteau", "Blazer",
    "Baskets", "Chaussures", "Sandales", "Bottes",
    "Sac", "Chapeau", "Lunettes", "Bijoux", "Ceinture", "Écharpe", "Montre",
]

SAISONS_VALIDES = ["Printemps", "Été", "Automne", "Hiver"]

OCCASIONS_VALIDES = ["vie quotidienne", "professionnel", "sport & loisirs", "soirée & évènement"]

PROMPT = """Tu es un expert en mode. Analyse cette image de façon très méticuleuse.

ÉTAPE 1 — Inspecte chaque zone de l'image dans cet ordre et liste CE QUE TU VOIS :
- Tête/cou : chapeau, lunettes (même tenues à la main), collier, écharpe ?
- Buste : haut, veste, blazer ?
- Taille : ceinture ?
- Bas du corps : pantalon, jupe, short, robe, salopette (= Combinaison) ?
- Poignets/mains : montre, bracelet, bague, sac ou pochette tenus en main ?
- Épaules/corps : sac en bandoulière ?
- Pieds : chaussures, baskets, sandales, bottes ?

IMPORTANT — classifications :
- Une salopette (avec bretelles) = Combinaison (pas Short)
- Un sac ou pochette tenu à la main = Sac
- Des lunettes tenues à la main = Lunettes
- Un collier fin = Bijoux

ÉTAPE 2 — Pour chaque élément identifié, fournis :
- type : valeur exacte parmi : T-shirt, Chemise, Pull, Sweat, Top, Polo, Jean, Pantalon, Short, Jupe, Jogging, Robe, Combinaison, Ensemble, Veste, Manteau, Blazer, Baskets, Chaussures, Sandales, Bottes, Sac, Chapeau, Lunettes, Bijoux, Ceinture, Écharpe, Montre
- couleur : couleur principale en français — toujours une valeur, jamais null
- saisons : liste parmi "Printemps", "Été", "Automne", "Hiver"
- marque : identifie la marque grâce aux indices visuels suivants (liste non exhaustive) :
    * Adidas : 3 bandes parallèles, logo trèfle (Originals) ou triangle
    * Nike : swoosh (virgule), "Just Do It", logo Air
    * New Balance : "N" sur le côté
    * Converse : étoile, semelle caoutchouc
    * Vans : bande latérale "jazz stripe"
    * Louis Vuitton : motif monogramme LV brun/beige
    * Gucci : double G entrelacé, bande verte-rouge-verte
    * Chanel : double C entrelacé, chaîne dorée
    * Coach : C entrelacé répété sur tissu
    * Fendi : FF entrelacé, motif baguette
    * Zara, H&M, Mango : logo texte visible sur étiquette ou pièce
    * Tommy Hilfiger : logo drapeau rouge/blanc/bleu, rayures tricolores
    * Ralph Lauren : logo polo petit cheval
    Fais une supposition si l'indice est visible même partiellement. Mettre null si vraiment aucun indice.

Pour l'occasion, donne 1 ou 2 valeurs parmi : "vie quotidienne", "professionnel", "sport & loisirs", "soirée & évènement"
Règles d'occasion :
- costume/tailleur/blazer/robe de soirée → "soirée & évènement"
- tenue de bureau, smart casual → "professionnel"
- jean/t-shirt/casual → "vie quotidienne"
- survêtement/legging/baskets de sport → "sport & loisirs"
- Si la tenue convient à plusieurs occasions, mets-en 2 maximum

Réponds UNIQUEMENT avec ce JSON, sans markdown :
{
  "vetements": [
    {"type": "...", "couleur": "...", "saisons": [], "marque": null}
  ],
  "style_global": "UN style parmi : Casual chic, Minimaliste, Classique, Streetwear, Bohème, Romantique, Élégant, Sportswear, Vintage, Smart casual, Preppy, Avant-garde",
  "occasions": ["vie quotidienne"]
}"""


def _image_to_base64(source: str) -> tuple[str, str]:
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
            ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".png": "image/png",  ".webp": "image/webp",
        }.get(ext, "image/jpeg")

    return base64.b64encode(data).decode("utf-8"), content_type


def analyser_tenue(source: str) -> dict:
    """
    Identifie tous les vêtements visibles sur une photo de tenue.

    Args:
        source : chemin local (str/Path) ou URL de la photo

    Returns:
        dict avec clés :
          - vetements : liste de dicts (type, couleur, saisons, marque)
          - style_global : style général de la tenue
          - occasion : occasion adaptée
    """
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY manquant dans .env")

    client = Groq(api_key=api_key)
    image_b64, media_type = _image_to_base64(str(source))

    response = client.chat.completions.create(
        model="meta-llama/llama-4-scout-17b-16e-instruct",
        max_tokens=1200,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{media_type};base64,{image_b64}"},
                    },
                    {"type": "text", "text": PROMPT},
                ],
            }
        ],
    )

    raw = response.choices[0].message.content.strip()
    raw = re.sub(r"^```json\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    result = json.loads(raw)

    # Filtrer et valider chaque vêtement
    vetements_valides = []
    for v in result.get("vetements", []):
        v["saisons"] = [s for s in v.get("saisons", []) if s in SAISONS_VALIDES]
        if not v.get("couleur"):
            v["couleur"] = "Couleur non déterminée"
        if v.get("type") in TYPES_VALIDES:
            vetements_valides.append(v)

    result["vetements"] = vetements_valides

    # Gérer occasions (liste ou string selon ce que le LLM retourne)
    occasions_raw = result.get("occasions") or result.get("occasion") or []
    if isinstance(occasions_raw, str):
        occasions_raw = [occasions_raw]
    occasions_valides = [o for o in occasions_raw if o in OCCASIONS_VALIDES][:2]
    result["occasions"] = occasions_valides if occasions_valides else ["vie quotidienne"]
    result.pop("occasion", None)

    # Valider le style global
    styles_valides = [
        "Casual chic", "Minimaliste", "Classique", "Streetwear", "Bohème",
        "Romantique", "Élégant", "Sportswear", "Vintage", "Smart casual",
        "Preppy", "Avant-garde",
    ]
    if result.get("style_global") not in styles_valides:
        result["style_global"] = "Casual chic"

    return result
