import random
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

from playwright.sync_api import Page, sync_playwright

import config


# ---------------------------------------------------------------------------
# Modèle de données produit (spécifique au scraping)
# ---------------------------------------------------------------------------

@dataclass
class Product:
    name: str
    price_value: Optional[float]
    currency: str
    description: str
    genre: str          # "Adultes" | "Adolescent" | "Enfant"
    sexe: str           # "Femme" | "Homme" | "Fille" | "Garçon"
    type: str           # "Vêtement" | "Chaussures" | "Autre"
    categorie: str      # "Haut" | "Bas" | "Haut/Bas" | "Accessoires"
    style: str          # "Jean" | "T-shirt" | "Pull" | ...
    sizes: list[str] = field(default_factory=list)
    color: Optional[list[str]] = None  # toutes les couleurs disponibles
    rating: Optional[float] = None
    image: Optional[str] = None
    url: str = ""
    brand: str = ""

    def to_dict(self) -> dict:
        return {
            "Name": self.name,
            "price_value": self.price_value,
            "Currency": self.currency,
            "Description": self.description,
            "Genre": self.genre,
            "Sexe": self.sexe,
            "Type": self.type,
            "Categorie": self.categorie,
            "Style": self.style,
            "Sizes": self.sizes,
            "Color": self.color,
            "Rating": self.rating,
            "Image": self.image,
            "Url": self.url,
            "Brand": self.brand,
        }


# ---------------------------------------------------------------------------
# Classe de base abstraite
# ---------------------------------------------------------------------------

class BaseScraper(ABC):
    """
    Classe de base pour tous les scrapers de marque.

    Chaque scraper enfant doit implémenter :
      - brand                   : nom de la marque (str)
      - get_targets()           : liste de (sexe_label, url, genre_category)
      - extract_product_links() : retourne les URLs produits depuis la page catalogue
      - extract_product()       : retourne un Product depuis une fiche produit
    """

    brand: str = ""
    browser_type: str = "firefox"  # "firefox" ou "chromium" — à surcharger si besoin

    def __init__(
        self,
        headless: bool = config.HEADLESS,
        max_products: int = config.MAX_PRODUCTS_PER_CATEGORY,
    ):
        self.headless = headless
        self.max_products = max_products

    # ------------------------------------------------------------------
    # Interface à implémenter
    # ------------------------------------------------------------------

    @abstractmethod
    def get_targets(self) -> list[tuple[str, str, str]]:
        """Retourne [(sexe_label, url_catalogue, genre_category), ...]"""

    @abstractmethod
    def extract_product_links(self, page: Page) -> list[str]:
        """Extrait les URLs des produits depuis la page catalogue courante."""

    @abstractmethod
    def extract_product(
        self, page: Page, link: str, sexe_label: str, genre_category: str
    ) -> Optional[Product]:
        """Extrait et retourne un Product depuis une fiche produit."""

    # ------------------------------------------------------------------
    # Boucle principale (toutes les cibles séquentielles)
    # ------------------------------------------------------------------

    def scrape(self) -> list[Product]:
        results: list[Product] = []
        for sexe_label, url, genre_category in self.get_targets():
            results.extend(self.scrape_one_target(sexe_label, url, genre_category))
        return results

    # ------------------------------------------------------------------
    # Scrape une seule cible (utilisé par le multiprocessing)
    # ------------------------------------------------------------------

    def accept_cookies(self, page: Page) -> None:
        """Hook optionnel : accepter les cookies. À surcharger dans chaque scraper."""
        pass

    def scrape_one_target(
        self, sexe_label: str, url: str, genre_category: str
    ) -> list[Product]:
        results: list[Product] = []

        with sync_playwright() as p:
            if self.browser_type == "chromium":
                browser = p.chromium.launch(
                    headless=self.headless,
                    args=["--disable-blink-features=AutomationControlled"],
                )
                context = browser.new_context(
                    viewport={"width": 1920, "height": 1080},
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/123.0.0.0 Safari/537.36"
                    ),
                    locale="fr-FR",
                    timezone_id="Europe/Paris",
                )
            else:
                browser = p.firefox.launch(
                    headless=self.headless,
                    firefox_user_prefs={
                        "general.platform.override": "Win32",
                        "intl.accept_languages": "fr-FR, fr, en-US, en",
                    },
                )
                context = browser.new_context(
                    viewport={"width": 1280, "height": 800},
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) "
                        "Gecko/20100101 Firefox/124.0"
                    ),
                    locale="fr-FR",
                    timezone_id="Europe/Paris",
                )
            # Masque les traces d'automation (headless stealth)
            context.add_init_script("""
                // 1. navigator.webdriver
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

                // 2. window.chrome (absent en headless Chromium)
                if (!window.chrome) {
                    window.chrome = { runtime: {}, loadTimes: function(){}, csi: function(){}, app: {} };
                }

                // 3. navigator.plugins (vide en headless)
                Object.defineProperty(navigator, 'plugins', {
                    get: () => ({ length: 3, 0: { name: 'PDF Viewer' }, 1: { name: 'Chrome PDF Viewer' }, 2: { name: 'Native Client' } })
                });

                // 4. navigator.languages
                Object.defineProperty(navigator, 'languages', {
                    get: () => ['fr-FR', 'fr', 'en-US', 'en']
                });

                // 5. Permissions (évite la détection via l'API Notifications)
                try {
                    const origQuery = navigator.permissions.query.bind(navigator.permissions);
                    navigator.permissions.query = (p) =>
                        p.name === 'notifications'
                            ? Promise.resolve({ state: 'denied', onchange: null })
                            : origQuery(p);
                } catch(e) {}
            """)
            page = context.new_page()

            print(f"\n→ [{self.brand}] Catalogue : {sexe_label}", flush=True)
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=90000)
                time.sleep(config.PAGE_LOAD_WAIT)

                # Accepte les cookies dès le chargement de la page catalogue
                self.accept_cookies(page)

                links = self.extract_product_links(page)
                print(f"  {len(links)} produit(s) trouvé(s) [{sexe_label}]", flush=True)

                for link in links:
                    print(f"  → {link}", flush=True)
                    # Délai aléatoire entre chaque produit (imite un comportement humain)
                    time.sleep(random.uniform(1.5, 3.5))

                    product = None
                    for attempt in range(1, 3):  # max 2 tentatives
                        try:
                            product = self.extract_product(page, link, sexe_label, genre_category)
                            if product and product.name:
                                break  # succès
                            print(f"     ↻ Tentative {attempt} vide, on réessaie...", flush=True)
                            time.sleep(3)
                        except Exception as e:
                            print(f"     ✗ Erreur (tentative {attempt}) : {e}", flush=True)
                            time.sleep(3)

                    if product and product.name:
                        results.append(product)
                        print(
                            f"     ✓ {product.name} | {product.style} "
                            f"| {len(product.sizes)} taille(s)"
                            + (f" | {product.color[0]}" if product.color else ""),
                            flush=True,
                        )
                    elif product:
                        print(f"     ✗ Ignoré (nom vide après 2 tentatives) : {link}", flush=True)

            except Exception as e:
                print(f"  ✗ Erreur catalogue {sexe_label} : {e}", flush=True)

            browser.close()

        return results

    # ------------------------------------------------------------------
    # Utilitaires partagés
    # ------------------------------------------------------------------

    KNOWN_SIZES = [
        # Tailles texte vêtements
        "XXS", "XS", "S", "M", "L", "XL", "XXL",
        # Tailles numériques vêtements adultes
        "32", "34", "36", "38", "40", "42", "44", "46", "48",
        "50", "52", "54", "56", "58", "60", "62",
        # Tailles numériques vêtements enfants / ados
        "22", "24", "26", "28", "30",
        # Tailles vêtements bébé/enfant (cm)
        "50/56", "62/68", "68", "74", "74/80", "80",
        "86", "86/92", "92", "98", "98/104", "104", "110", "110/116",
        "116", "122", "122/128", "128", "134", "134/140", "140",
        "146", "146/152", "152", "158", "158/164", "164", "170",
        # Pointures chaussures (enfant → adulte : 15 à 45)
        "15", "16", "17", "18", "19", "20", "21", "22", "23", "24", "25",
        "26", "27", "28", "29", "30", "31", "32", "33", "34", "35",
        "36", "37", "38", "39", "40", "41", "42", "43", "44", "45",
    ]

    _CATEGORY_RULES: list[tuple[str, str, str, str]] = [
        (r"jean",                               "Vêtement",    "Bas",           "Jean"),
        (r"t-shirt|tee shirt",                  "Vêtement",    "Haut",          "T-shirt"),
        (r"pull|cardigan|gilet",                "Vêtement",    "Haut",          "Pull"),
        (r"sweat|sweatshirt",                   "Vêtement",    "Haut",          "Sweat"),
        (r"chemise|blouse",                     "Vêtement",    "Haut",          "Chemise"),
        (r"polo",                              "Vêtement",    "Haut",           "Polo"),
        (r"pantalon|legging",                   "Vêtement",    "Bas",           "Pantalon"),
        (r"sweatpants|jogging",                 "Vêtement",    "Bas",           "Jogging"),
        (r"robe",                               "Vêtement",    "Ensemble",      "Robe"),
        (r"combinaison",                        "Vêtement",    "Ensemble",      "Combinaison"),
        (r"débardeur|\btop\b",                  "Vêtement",    "Haut",          "Top"),
        (r"crop-top",                           "Vêtement",    "Haut",          "Crop-top"),
        (r"veste|manteau|blazer|blouson",       "Vêtement",    "Haut",          "Veste/Manteau"),
        (r"short|bermuda|short en jean",        "Vêtement",    "Bas",           "Short"),
        (r"jupe|jupe-short",                    "Vêtement",    "Bas",           "Jupe"),
        (r"collier|boucles d'oreilles|bracelet|montre|piercing", "Accessoires", "Accessoires", "Bijoux"),
        (r"ceinture",                           "Accessoires", "Accessoires",   "Ceinture"),
        (r"sac",                                "Accessoires", "Accessoires",   "Sac"),
        (r"casquette|bob|chapeau",              "Accessoires", "Accessoires",   "Chapeau"),
        (r"boxer|culotte|slip|chaussette|chaussettes|collant", "Vêtement", "Sous-vêtement", "Sous-vêtement"),
        (r"chaussure|chaussures",               "Chaussures",  "Chaussures",    "Chaussures"),
        (r"botte|bottes",                       "Chaussures",  "Chaussures",    "Bottes"),
        (r"bottine|bottines",                   "Chaussures",  "Chaussures",    "Bottines"),
        (r"santiags",                           "Chaussures",  "Chaussures",    "Santiags"),
        (r"sandales",                           "Chaussures",  "Chaussures",    "Sandales"),
        (r"claquettes|tongs",                   "Chaussures",  "Chaussures",    "Claquettes/Tongs"),
        (r"escarpins",                          "Chaussures",  "Chaussures",    "Escarpins"),
        (r"mocassins",                          "Chaussures",  "Chaussures",    "Mocassins"),
        (r"basket|baskets|sneakers",            "Chaussures",  "Chaussures",    "Baskets"),
    ]

    @classmethod
    def detect_category(cls, full_text: str) -> tuple[str, str, str]:
        """Retourne (type, categorie, style) à partir du texte nom+description."""
        text = full_text.lower()
        for pattern, type_, cat, style in cls._CATEGORY_RULES:
            if re.search(pattern, text):
                return type_, cat, style
        return "Autre", "Accessoires", "Autre"
