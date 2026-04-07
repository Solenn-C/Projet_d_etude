"""
Pipeline de scraping.
Orchestre l'exécution d'un ou plusieurs scrapers et sauvegarde les résultats.
Utilise le multiprocessing pour scraper chaque section (Femme/Homme/Enfant) en parallèle.
"""

import json
from multiprocessing import Pool
from pathlib import Path

import config
from scrapers.base import Product
from scrapers.init import get_scraper


# ---------------------------------------------------------------------------
# Fonction exécutée dans chaque processus fils
# Doit être définie au niveau module pour être picklable par multiprocessing
# ---------------------------------------------------------------------------

def _scrape_target(args: tuple) -> list[dict]:
    brand, sexe_label, url, genre_category, scraper_kwargs = args
    scraper = get_scraper(brand, **scraper_kwargs)
    products = scraper.scrape_one_target(sexe_label, url, genre_category)
    # On retourne des dicts car les dataclasses ne sont pas toujours bien transmises entre processus
    return [p.to_dict() for p in products]


# ---------------------------------------------------------------------------
# Pipeline principal
# ---------------------------------------------------------------------------

def run(brands: list[str], workers: int = 3, **scraper_kwargs) -> list[Product]:
    """
    Lance le scraping pour chaque marque.
    Les sections (Femme/Homme/Enfant) de chaque marque tournent en parallèle.

    Args:
        brands      : liste de marques, ex. ["hm"]
        workers     : nombre de processus parallèles (défaut : 3, une par section)
        **scraper_kwargs : options transmises aux scrapers (headless, max_products, …)
    """
    from scrapers.base import Product as P

    all_products: list[dict] = []

    for brand in brands:
        print(f"\n{'='*50}", flush=True)
        print(f"  Scraping : {brand.upper()}", flush=True)
        print(f"{'='*50}", flush=True)

        # Récupère les cibles sans lancer de navigateur
        scraper = get_scraper(brand, **scraper_kwargs)
        targets = scraper.get_targets()

        # Prépare les arguments pour chaque processus fils
        task_args = [
            (brand, sexe_label, url, genre_category, scraper_kwargs)
            for sexe_label, url, genre_category in targets
        ]

        if not task_args:
            print(f"  Aucune cible définie pour {brand.upper()}", flush=True)
            continue

        nb_workers = min(workers, len(task_args))
        print(f"  {len(task_args)} section(s) → {nb_workers} processus parallèles", flush=True)

        with Pool(processes=nb_workers) as pool:
            results = pool.map(_scrape_target, task_args)

        for product_dicts in results:
            all_products.extend(product_dicts)

        print(f"  → {sum(len(r) for r in results)} produit(s) récupéré(s) pour {brand.upper()}", flush=True)

    return all_products


def save(products: list[dict], filename: str) -> Path:
    """Sauvegarde la liste de produits en JSON dans OUTPUT_DIR."""
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = config.OUTPUT_DIR / filename

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(products, f, indent=4, ensure_ascii=False)

    print(f"\n✓ {len(products)} produit(s) sauvegardé(s) → {output_path}", flush=True)
    return output_path
