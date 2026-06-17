"""
Reclassifie les produits mal classés dans PostgreSQL en se basant
sur des règles par mots-clés dans le nom du produit.

Usage :
    python scripts/reclassify.py --preview     # affiche les changements sans modifier la BDD
    python scripts/reclassify.py --apply       # applique les changements
    python scripts/reclassify.py --preview --brand asos  # filtre sur une marque
"""

import argparse
import os
import re
import sys
from collections import defaultdict

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

# ---------------------------------------------------------------------------
# Règles de reclassification
# Ordre important : les règles plus spécifiques doivent être en premier.
# Chaque règle : (pattern_regex, nouveau_style)
# On cherche dans le nom du produit (insensible à la casse).
# ---------------------------------------------------------------------------

RULES: list[tuple[str, str]] = [
    # Chaussures
    (r"\bclaquette[s]?\b|\btong[s]?\b",                                                                     "Claquettes/Tongs"),
    (r"\bsandale[s]?\b|\bnu[- ]pied[s]?\b|\bslipper[s]?\b",                                                "Sandales"),
    (r"\bbottine[s]?\b|\bchukka\b|\bchelsei?\b",                                                            "Bottines"),
    (r"\bbotte[s]?\b",                                                                                       "Bottes"),
    (r"\bmocassin[s]?\b|\bloafer[s]?\b|\bmonk[- ]strap\b",                                                  "Mocassins"),
    (r"\bbasket[s]?\b|\bsneaker[s]?\b",                                                                     "Baskets"),
    (r"\bchaussure[s]?\b|\bderby\b|\bescarpin[s]?\b|\bbalerine[s]?\b|\bmule[s]?\b|\bsabot[s]?\b|\boxford[s]?\b|\beslip[- ]on[s]?\b", "Chaussures"),
    # Sous-vêtements
    (r"\bcale[çc]on[s]?\b|\bboxer[s]?\b|\bslip[s]?\b|\bstring[s]?\b|\btanga[s]?\b|\bthong[s]?\b",          "Sous-vêtement"),
    (r"\bsoutien[- ]gorge\b|\bbralette[s]?\b|\bnuisette[s]?\b|\bchaussette[s]?\b|\bsocquette[s]?\b",       "Sous-vêtement"),
    # Accessoires
    (r"\bchapeau[x]?\b|\bbob[s]?\b|\bcasquette[s]?\b|\bbeanie[s]?\b|\bbonnet[s]?\b(?!\s+de\s+bain)|\bfedora\b|\bstetson\b", "Chapeau"),
    (r"\bceinture[s]?\b|\bbelt[s]?\b",                                                                      "Ceinture"),
    (r"\bcravate[s]?\b|\bnoeud[s]?\s+pap|\bnœud[s]?\s+pap|\bbow[- ]tie\b|\bgarvroche\b|\bgavroche\b",      "Cravate/Noeud"),
    (r"\bgant[s]?\b|\bmoufle[s]?\b",                                                                        "Gants"),
    (r"\bécharpe[s]?\b|\bfoulard[s]?\b|\bcache[- ]col\b|\bsnood\b|\bbandana[s]?\b|\bpasshmina\b|\btour\s+de\s+cou\b", "Écharpe/Foulard"),
    (r"\blunette[s]?\b",                                                                                     "Lunettes"),
    (r"\bmaillot[s]?\b",                                                                                     "Maillot"),
    (r"\bbagage[s]?\b|\bvalise[s]?\b|\bsac[s]?\s+de\s+sport\b|\bsac[s]?\s+à\s+dos\b|\bbackpack\b",        "Sac"),
    (r"\bsac[s]?\b(?!\s+de\s+sport)|\bcabas\b|\btote\b|\bcrossbody\b|\bclutch\b|\bpochette[s]?\b|\bportefeuille[s]?\b", "Sac"),
    (r"\bclou[s]?\s+d.oreille|\bcréole[s]?\b|\banneau[x]?\b|\boreille[s]?\b",                              "Bijoux"),
    (r"\bbijou[x]?\b|\bcollier[s]?\b|\bbracelet[s]?\b|\bbague[s]?\b|\bboucle[s]?\s+d.oreille|\bpendentif[s]?\b|\bbarrette[s]?\b", "Bijoux"),
    # Ensemble & Pyjama
    (r"\bensemble\b|\bpyjama[s]?\b",                                                                        "Ensemble"),
    # Robes & Combinaisons
    (r"\brobe[s]?\b|\bmaxi[- ]robe[s]?\b",                                                                  "Robe"),
    (r"\bsalopette[s]?\b|\bjumpsuit[s]?\b|\bplaysuit[s]?\b|\bcombinaison[s]?\b|\bgrenouillère[s]?\b|\bsurpyjama[s]?\b", "Combinaison"),
    # Vestes & Manteaux
    (r"\bblouson[s]?\b|\bbomber[s]?\b|\bdoudoune[s]?\b|\bparka[s]?\b|\btrench[s]?\b|\bmanteau[x]?\b|\bimperméable[s]?\b|\banorak[s]?\b|\bcaban[s]?\b|\bcoupe[- ]vent\b|\bsoftshell\b", "Veste/Manteau"),
    (r"\bveste[s]?\b|\bblazer[s]?\b|\bveston[s]?\b|\bsurchemise[s]?\b",                                    "Veste/Manteau"),
    # Hauts
    (r"\bchemise[s]?\b|\bchemisette[s]?\b|\bchemisier[s]?\b|\bblouse[s]?\b",                               "Chemise"),
    (r"\bsweat[s]?\b|\bsweatshirt[s]?\b|\bhoodie[s]?\b",                                                   "Sweat"),
    (r"\bpolo[s]?\b",                                                                                       "Polo"),
    (r"\bt[\-\s]?shirt[s]?\b|\btee[\-\s]?shirt[s]?\b",                                                     "T-shirt"),
    (r"\bpull[s]?\b|\bpullover[s]?\b|\btricot[s]?\b|\bcardigan[s]?\b|\bgilet[s]?\b(?!\s+de\s+sport)",      "Pull"),
    (r"\bbody\b|\bbodies\b|\bbodys\b|\bbodysuit\b|\bcaraco[s]?\b|\bdébardeur[s]?\b|\bdebardeur[s]?\b|\bcrop[- ]top\b|\btank[- ]top\b|\btop[s]?\b|\bhaut[s]?\b", "Top"),
    # Bas
    (r"\bjegging[s]?\b",                                                                                    "Pantalon"),
    (r"\bbermuda[s]?\b|\bshort[s]?\b",                                                                      "Short"),
    (r"\bminijupe[s]?\b|\bjupe[s]?\b|\bskirt[s]?\b",                                                        "Jupe"),
    (r"\bjogging[s]?\b|\bsurv[eê]tement[s]?\b|\bsurvêt\b",                                                 "Jogging"),
    (r"\bpantalon[s]?\b|\blegging[s]?\b|\bjogger[s]?\b|\bchino[s]?\b|\bsarouel[s]?\b",                     "Pantalon"),
    (r"\bjean[s]?\b",                                                                                       "Jean"),
    # Denim en dernier recours
    (r"\bdenim\b",                                                                                          "Jean"),
    # Culotte dans jupe-culotte → géré par position (jupe apparaît avant culotte)
    (r"\bculotte[s]?\b",                                                                                    "Sous-vêtement"),
]

# Règles compilées
_COMPILED: list[tuple[re.Pattern, str]] = [
    (re.compile(pat, re.IGNORECASE), style)
    for pat, style in RULES
]


def classify_by_name(name: str) -> str | None:
    """
    Retourne le style prédit à partir du nom.
    Stratégie : on prend le mot-clé qui apparaît le PLUS TÔT dans le nom.
    En cas d'égalité de position, l'ordre des règles sert de départage.
    """
    best_start = len(name) + 1
    best_style = None
    for pattern, style in _COMPILED:
        m = pattern.search(name)
        if m and m.start() < best_start:
            best_start = m.start()
            best_style = style
    return best_style


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--preview", action="store_true", help="Affiche les changements sans modifier la BDD")
    group.add_argument("--apply",   action="store_true", help="Applique les changements en base")
    parser.add_argument("--brand",  help="Filtrer sur une marque (ex: asos)")
    parser.add_argument("--show-unchanged", action="store_true", help="Affiche aussi les produits non modifiés")
    return parser.parse_args()


def main():
    args = parse_args()

    if not DATABASE_URL:
        print("DATABASE_URL manquant dans .env")
        sys.exit(1)

    engine = create_engine(DATABASE_URL, echo=False)

    with Session(engine) as session:
        where = "WHERE style IS NOT NULL"
        params = {}
        if args.brand:
            where += " AND LOWER(brand) = :brand"
            params["brand"] = args.brand.lower()

        rows = session.execute(
            text(f"SELECT id, name, brand, style FROM products {where} ORDER BY style, name"),
            params
        ).fetchall()

    print(f"{len(rows)} produits chargés\n")

    changes: list[tuple[int, str, str, str]] = []   # (id, name, old_style, new_style)
    by_change: dict[str, list] = defaultdict(list)  # (old→new) → list of names

    for product_id, name, brand, old_style in rows:
        new_style = classify_by_name(name or "")
        if new_style and new_style != old_style:
            changes.append((product_id, name, old_style, new_style))
            key = f"{old_style} → {new_style}"
            by_change[key].append(f"[{brand}] {name}")
        elif args.show_unchanged and new_style is None:
            print(f"  ? [{old_style}] {name[:80]}")

    # --- Résumé des changements ---
    print(f"{'='*60}")
    print(f"{len(changes)} produits à reclassifier\n")
    for key in sorted(by_change):
        items = by_change[key]
        print(f"  {key} ({len(items)} produits)")
        for item in items[:5]:
            print(f"      • {item[:80]}")
        if len(items) > 5:
            print(f"      ... et {len(items)-5} autres")
        print()

    if args.preview:
        print("Mode PREVIEW — aucune modification en base.")
        print("Relance avec --apply pour appliquer.")
        return

    # --- Application ---
    if not changes:
        print("Rien à modifier.")
        return

    confirm = input(f"\nAppliquer {len(changes)} modifications ? [o/N] ").strip().lower()
    if confirm != "o":
        print("Annulé.")
        return

    with Session(engine) as session:
        for product_id, name, old_style, new_style in changes:
            session.execute(
                text("UPDATE products SET style = :new WHERE id = :id"),
                {"new": new_style, "id": product_id}
            )
        session.commit()

    print(f"\n{len(changes)} produits reclassifiés avec succès.")


if __name__ == "__main__":
    main()
