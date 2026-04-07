"""
Scraper Le Coq Sportif — utilise l'API JSON Shopify native.
Aucun navigateur requis : requêtes HTTP directes.
"""

import re
import time
from typing import Optional

import requests
from playwright.sync_api import Page

from scrapers.base import BaseScraper, Product


def _strip_html(html: str) -> str:
    """Supprime les balises HTML et nettoie le texte."""
    text = re.sub(r"<[^>]+>", " ", html or "")
    return re.sub(r"\s+", " ", text).strip()


class LeCoqSportifScraper(BaseScraper):
    """Scraper pour Le Coq Sportif via l'API Shopify."""

    brand       = "Le Coq Sportif"
    browser_type = "firefox"  # non utilisé ici mais requis par BaseScraper

    _BASE_URL = "https://www.lecoqsportif.com"
    _HEADERS  = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) "
            "Gecko/20100101 Firefox/124.0"
        ),
        "Accept": "application/json",
        "Accept-Language": "fr-FR,fr;q=0.9",
    }

    def get_targets(self) -> list[tuple[str, str, str]]:
        return [
            ("Femme",   "femme",   "Adultes"),
            ("Homme",   "homme",   "Adultes"),
            ("Enfant", "enfant",  "Enfant"),
        ]

    # ------------------------------------------------------------------
    # Override : pas de Playwright, on utilise l'API Shopify directement
    # ------------------------------------------------------------------

    def scrape_one_target(
        self, sexe_label: str, url: str, genre_category: str
    ) -> list[Product]:
        """url est ici le slug de collection (ex: 'femme')."""
        results: list[Product] = []
        collection  = url  # ex: "femme"
        page_num    = 1
        limit       = 250  # max Shopify

        print(f"\n→ [{self.brand}] Catalogue : {sexe_label}", flush=True)

        while len(results) < self.max_products:
            api_url = (
                f"{self._BASE_URL}/collections/{collection}/products.json"
                f"?limit={limit}&page={page_num}"
            )
            try:
                resp = requests.get(api_url, headers=self._HEADERS, timeout=30)
                if resp.status_code != 200:
                    print(f"  ✗ HTTP {resp.status_code} — arrêt", flush=True)
                    break
                products_json = resp.json().get("products", [])
            except Exception as e:
                print(f"  ✗ Erreur requête : {e}", flush=True)
                break

            if not products_json:
                break  # plus de produits

            for p in products_json:
                if len(results) >= self.max_products:
                    break

                product = self._parse_product(p, sexe_label, genre_category)
                if product:
                    results.append(product)
                    print(
                        f"  ✓ {product.name} | {product.style} "
                        f"| {len(product.sizes)} taille(s)"
                        + (f" | {product.color[0]}" if product.color else ""),
                        flush=True,
                    )

            print(f"  {len(results)} produits récupérés (page {page_num})", flush=True)

            if len(products_json) < limit:
                break  # dernière page
            page_num += 1
            time.sleep(0.5)  # pause polie entre les pages

        return results

    # ------------------------------------------------------------------
    # Parse un produit depuis la réponse Shopify
    # ------------------------------------------------------------------

    def _parse_product(
        self, p: dict, sexe_label: str, genre_category: str
    ) -> Optional[Product]:
        name = p.get("title", "").strip()
        if not name:
            return None

        # Description (body_html → texte brut)
        desc = _strip_html(p.get("body_html") or "")[:500]

        # Prix (depuis le premier variant)
        price = None
        variants = p.get("variants", [])
        if variants:
            try:
                price = float(variants[0].get("price", 0) or 0) or None
            except (ValueError, TypeError):
                price = None

        # Tailles et couleurs depuis les options Shopify
        _SIZE_BLOCKLIST = {"SPL", "Default Title", "N/A", "OS", "ONE SIZE"}
        sizes:  list[str] = []
        colors: list[str] = []
        for opt in p.get("options", []):
            opt_name = opt.get("name", "").lower()
            values   = [v for v in opt.get("values", []) if v and v not in _SIZE_BLOCKLIST]
            if any(k in opt_name for k in ("taille", "size", "pointure")):
                sizes = values
            elif any(k in opt_name for k in ("couleur", "color", "colour", "coloris")):
                colors = values

        # Couleur : 2. depuis les titres des variants (ex: "XS / Noir")
        # On considère qu'une valeur est une taille si elle est dans KNOWN_SIZES
        # ou ressemble à une taille enfant (ex: "4A", "2-3 ans", "86/92")
        _known = set(s.upper() for s in self.KNOWN_SIZES)
        _size_re = re.compile(
            r"^\d+[A-Za-z]$|"           # 4A, 6A, 12A...
            r"^\d+-\d+\s*(ans?|mois)$|" # 2-3 ans, 6-9 mois
            r"^\d+/\d+$",               # 86/92, 98/104
            re.IGNORECASE
        )
        if not colors:
            for v in variants:
                title = v.get("title", "")
                for part in title.split("/"):
                    part = part.strip()
                    if (part
                            and part not in _SIZE_BLOCKLIST
                            and part.upper() not in _known
                            and not _size_re.match(part)):
                        colors.append(part)
            colors = list(dict.fromkeys(colors))  # dédoublonnage

        # Couleur : 3. depuis les tags du produit (ex: "couleur_noir")
        if not colors:
            tags = p.get("tags", [])
            for tag in (tags if isinstance(tags, list) else tags.split(",")):
                tag = tag.strip().lower()
                for prefix in ("couleur_", "color_", "coloris_"):
                    if tag.startswith(prefix):
                        colors = [tag.replace(prefix, "").capitalize()]
                        break

        # Couleur : 4. mots-clés dans titre + description
        if not colors:
            _COLOR_KEYWORDS = [
                "noir", "blanc", "rouge", "bleu", "vert", "jaune", "orange",
                "rose", "violet", "gris", "beige", "marron", "kaki", "marine",
                "turquoise", "bordeaux", "écru", "crème", "anthracite", "camel",
                "black", "white", "red", "blue", "green", "navy",
            ]
            search_text = (name + " " + desc).lower()
            found = [c for c in _COLOR_KEYWORDS if re.search(r'\b' + c + r'\b', search_text)]
            if found:
                colors = [found[0].capitalize()]

        # Image principale
        images = p.get("images", [])
        image  = images[0].get("src") if images else None

        # URL produit
        handle = p.get("handle", "")
        url    = f"{self._BASE_URL}/products/{handle}" if handle else ""

        # Catégorie
        full_text = (name + " " + desc).lower()
        type_, categorie, style = self.detect_category(full_text)

        return Product(
            name        = name,
            price_value = price,
            currency    = "€",
            description = desc,
            genre       = genre_category,
            sexe        = sexe_label,
            type        = type_,
            categorie   = categorie,
            style       = style,
            sizes       = sizes,
            color       = colors or None,
            rating      = None,
            image       = image,
            url         = url,
            brand       = self.brand,
        )

    # ------------------------------------------------------------------
    # Méthodes abstraites non utilisées (API remplace Playwright)
    # ------------------------------------------------------------------

    def accept_cookies(self, page: Page) -> None:
        pass

    def extract_product_links(self, page: Page) -> list[str]:
        return []

    def extract_product(self, page, link, sexe_label, genre_category):
        return None
