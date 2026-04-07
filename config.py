from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output"

# ---------------------------------------------------------------------------
# Scraping behaviour
# ---------------------------------------------------------------------------
HEADLESS = False                 # Garder False : headless augmente le risque de blocage anti-bot
MAX_PRODUCTS_PER_CATEGORY = 20  # Nombre de produits scrapés par section
PAGE_LOAD_WAIT = 8              # Secondes d'attente après chargement du catalogue
PRODUCT_LOAD_WAIT = 5           # Secondes d'attente après chargement d'une fiche produit
CONCURRENCY = 5                 # Nombre de fiches produits scrapées en parallèle
