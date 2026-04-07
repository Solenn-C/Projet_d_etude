"""
Point d'entrée principal.

Exemples d'utilisation :
    python main.py --brands hm                            # 3 sections en parallèle
    python main.py --brands hm --headless                 # sans fenêtre navigateur
    python main.py --brands hm --max 100                  # 100 produits par section
    python main.py --brands hm --workers 2                # 2 processus parallèles
    python main.py --brands hm --max 100 --output hm.json
"""

import argparse

import pipeline
from scrapers.init import SCRAPERS


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scraper de vêtements")
    parser.add_argument(
        "--brands",
        nargs="+",
        default=list(SCRAPERS.keys()),
        choices=list(SCRAPERS.keys()),
        help="Marques à scraper (défaut : toutes)",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Lancer les navigateurs en arrière-plan",
    )
    parser.add_argument(
        "--max",
        type=int,
        default=20,
        dest="max_products",
        help="Nombre max de produits par section (défaut : 20)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=3,
        help="Nombre de sections scrapées en parallèle (défaut : 3)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Nom du fichier de sortie dans output/ (défaut : <marque>.json ou scraping_results.json)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    products = pipeline.run(
        brands=args.brands,
        workers=args.workers,
        headless=args.headless,
        max_products=args.max_products,
    )

    if args.output:
        filename = args.output
    elif len(args.brands) == 1:
        filename = f"{args.brands[0]}_complet.json"
    else:
        filename = "scraping_results.json"

    pipeline.save(products, filename)
