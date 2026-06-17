"""
Classifie le style_mode de chaque produit en base via l'API Claude.

Usage :
    python scripts/classify_style.py --preview     # teste sur 5 produits
    python scripts/classify_style.py --apply       # classifie tous les produits sans style_mode
    python scripts/classify_style.py --apply --brand mango  # filtre sur une marque
"""

import argparse
import os
import sys
import time

import anthropic
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

load_dotenv()

DATABASE_URL  = os.getenv("DATABASE_URL")
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY")

STYLES = [
    "Casual chic",
    "Minimaliste",
    "Classique",
    "Streetwear",
    "Bohème",
    "Romantique",
    "Élégant",
    "Sportswear",
    "Vintage",
    "Smart casual",
    "Preppy",
    "Avant-garde",
]

STYLE_DESCRIPTIONS = """- Streetwear : hoodie, sweat à capuche, pièces oversized, jogger, sneakers, inspirations urbaines/skate/hip-hop. PAS élégant.
- Sportswear : vêtements techniques de sport, legging de sport, maillot, survêtement fonctionnel, pensé pour le mouvement physique.
- Casual chic : décontracté MAIS avec une touche soignée/élégante. Ex : blazer décontracté, chemise ouverte sur un jean, robe casual habillée. Jamais un simple sweat basique.
- Minimaliste : basiques épurés, couleurs neutres (blanc, noir, beige, gris), lignes simples et structurées, sans ornements.
- Classique : tailoring, costume, manteau cintré, vêtements intemporels et sobres, coupes précises.
- Smart casual : entre formel et décontracté, idéal bureau ou dîner. Ex : pantalon chino + chemise, blazer + jean.
- Élégant : sophistiqué, formel, pour occasions habillées. Robes de soirée, tailleurs, matières nobles.
- Preppy : inspiré campus américain, couleurs vives, polo, blazer rayé, pantalon pastel, coupes nettes.
- Romantique : dentelles, fleurs, volants, couleurs douces (rose, lilas), touches féminines et délicates.
- Bohème : fluidité, imprimés ethniques/naturels, superpositions, matières naturelles, style libre.
- Vintage : inspirations rétro (70s, 80s, 90s), coupes d'époque revisitées, look nostalgique.
- Avant-garde : créatif, audacieux, asymétrique, formes et matières inattendues, mode expérimentale."""

SYSTEM_PROMPT = f"""Tu es un expert en mode. Tu dois classer un vêtement dans exactement UN des styles suivants :

{STYLE_DESCRIPTIONS}

RÈGLES IMPORTANTES :
- Un sweat à capuche basique = Streetwear (jamais Casual chic)
- Un t-shirt basique uni = Minimaliste (si couleur neutre) ou Streetwear (si graphique/logo)
- Un jean flare = Vintage
- Une veste de sport technique = Sportswear
- Casual chic nécessite une touche d'élégance, pas juste du confort

Réponds UNIQUEMENT avec le nom exact du style parmi cette liste, rien d'autre :
Casual chic, Minimaliste, Classique, Streetwear, Bohème, Romantique, Élégant, Sportswear, Vintage, Smart casual, Preppy, Avant-garde"""


def classify_product(client: anthropic.Anthropic, name: str, description: str, style: str, brand: str) -> str | None:
    user_msg = f"""Marque : {brand}
Type de vêtement : {style}
Nom : {name}
Description : {description or "Non disponible"}

Quel est le style_mode de ce vêtement ?"""

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=20,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        result = response.content[0].text.strip()
        if result in STYLES:
            return result
        # Tentative de correspondance approximative
        for s in STYLES:
            if s.lower() in result.lower():
                return s
        return None
    except Exception as e:
        print(f"  Erreur API : {e}")
        return None


def parse_args():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--preview", action="store_true", help="Teste sur 5 produits sans modifier la BDD")
    group.add_argument("--apply",   action="store_true", help="Classifie tous les produits sans style_mode")
    parser.add_argument("--brand",  help="Filtrer sur une marque (ex: mango)")
    parser.add_argument("--limit",  type=int, default=0, help="Nombre max de produits à traiter (0 = tous)")
    return parser.parse_args()


def main():
    args = parse_args()

    if not DATABASE_URL:
        print("DATABASE_URL manquant dans .env")
        sys.exit(1)
    if not ANTHROPIC_KEY:
        print("ANTHROPIC_API_KEY manquant dans .env")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    engine = create_engine(DATABASE_URL, echo=False)

    # Ajouter la colonne si elle n'existe pas encore
    with engine.connect() as conn:
        conn.execute(text("""
            ALTER TABLE products
            ADD COLUMN IF NOT EXISTS style_mode VARCHAR(50)
        """))
        conn.commit()

    # Récupérer les produits sans style_mode
    with Session(engine) as session:
        where = "WHERE style_mode IS NULL"
        params = {}
        if args.brand:
            where += " AND LOWER(brand) = :brand"
            params["brand"] = args.brand.lower()

        limit_clause = "LIMIT 5" if args.preview else (f"LIMIT {args.limit}" if args.limit else "")

        rows = session.execute(
            text(f"SELECT id, name, description, style, brand FROM products {where} ORDER BY id {limit_clause}"),
            params
        ).fetchall()

    print(f"{len(rows)} produits à classifier\n")

    results = []
    for i, (product_id, name, description, style, brand) in enumerate(rows, 1):
        style_mode = classify_product(client, name or "", description or "", style or "", brand or "")
        results.append((product_id, name, style, style_mode))
        status = style_mode or "?"
        print(f"  [{i}/{len(rows)}] {(name or '')[:50]:50s} → {status}")
        time.sleep(0.15)  # ~6 req/s, en dessous des limites Haiku

    print(f"\n{'='*60}")
    classified = [(pid, n, s, sm) for pid, n, s, sm in results if sm]
    print(f"{len(classified)}/{len(results)} produits classifiés\n")

    if args.preview:
        print("Mode PREVIEW — aucune modification en base.")
        return

    if not classified:
        print("Rien à enregistrer.")
        return

    with Session(engine) as session:
        for product_id, _, _, style_mode in classified:
            session.execute(
                text("UPDATE products SET style_mode = :sm WHERE id = :id"),
                {"sm": style_mode, "id": product_id}
            )
        session.commit()

    print(f"{len(classified)} produits mis à jour en base.")


if __name__ == "__main__":
    main()
