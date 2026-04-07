"""
Registre des scrapers disponibles.
Permet à pipeline.py de résoudre un scraper par son nom de marque.
"""

from scrapers.hm import HMScraper
from scrapers.asos import AsosScraper
from scrapers.zara import ZaraScraper
from scrapers.lecoqsportif import LeCoqSportifScraper
from scrapers.jules import JulesScraper

SCRAPERS: dict[str, type] = {
    "hm":            HMScraper,
    "asos":          AsosScraper,
    "zara":          ZaraScraper,
    "lecoqsportif":  LeCoqSportifScraper,
    "jules":         JulesScraper,
}


def get_scraper(brand: str, **kwargs):
    """
    Retourne une instance du scraper correspondant à la marque.

    Exemple :
        scraper = get_scraper("hm", headless=True, max_products=50)
    """
    brand = brand.lower()
    if brand not in SCRAPERS:
        raise ValueError(f"Marque inconnue : '{brand}'. Disponibles : {list(SCRAPERS.keys())}")
    return SCRAPERS[brand](**kwargs)
