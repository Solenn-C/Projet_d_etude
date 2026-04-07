import random
import re
import time
from typing import Optional

from playwright.sync_api import Page

import config
from scrapers.base import BaseScraper, Product


class ZaraScraper(BaseScraper):
    """Scraper pour Zara (fr/fr)."""

    brand = "Zara"

    def get_targets(self) -> list[tuple[str, str, str]]:
        return [
            ("Homme",    "https://www.zara.com/fr/fr/homme-tout-l7465.html?v1=2443335",              "Adultes"),
            ("Femme",    "https://www.zara.com/fr/fr/search?searchTerm=femme&section=WOMAN",          "Adultes"),
            ("Fille",    "https://www.zara.com/fr/fr/enfants-fille-collection-l7289.html?v1=2426193", "Enfant"),
            ("Garçon",   "https://www.zara.com/fr/fr/kids-boy-collection-l5413.html?v1=2426702",      "Enfant"),
            ("Fille",    "https://www.zara.com/fr/fr/kids-babygirl-collection-l5415.html?v1=2422053", "Enfant"),
            ("Garçon",   "https://www.zara.com/fr/fr/kids-babyboy-collection-l5414.html?v1=2422703",  "Enfant"),
            ("Unisexe",  "https://www.zara.com/fr/fr/kids-mini-view-all-l6750.html?v1=2428166",       "Enfant"),
            ("Unisexe",  "https://www.zara.com/fr/fr/enfants-accessoires-l3.html?v1=2435086",         "Enfant"),
        ]

    # ------------------------------------------------------------------
    # Cookies
    # ------------------------------------------------------------------

    def accept_cookies(self, page: Page) -> None:
        try:
            btn = page.locator(
                'button:has-text("Accepter"), button:has-text("Accept"), '
                'button:has-text("Tout accepter"), #onetrust-accept-btn-handler'
            ).first
            if btn.is_visible(timeout=5000):
                btn.click()
                time.sleep(1)
                print("    ✓ Cookies acceptés", flush=True)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Extraction des liens produits (scroll yo-yo)
    # ------------------------------------------------------------------

    def extract_product_links(self, page: Page) -> list[str]:
        """Scroll infini yo-yo pour charger tous les produits Zara."""
        last_height = page.evaluate("document.body.scrollHeight")
        consecutive_no_growth = 0
        collected = 0

        while consecutive_no_growth < 4:
            # Scroll vers le bas par paliers
            for _ in range(5):
                page.mouse.wheel(0, 2000)
                time.sleep(0.8)

            # Léger scroll arrière (yo-yo) pour déclencher le lazy load
            page.mouse.wheel(0, -500)
            time.sleep(1.5)

            new_height = page.evaluate("document.body.scrollHeight")
            current_links: int = page.evaluate(r"""() =>
                new Set(
                    Array.from(document.querySelectorAll('a'))
                        .map(a => a.href)
                        .filter(h => h && h.includes('-p') && /-p\d{8,}\.html/.test(h))
                ).size
            """)

            if new_height == last_height:
                consecutive_no_growth += 1
            else:
                consecutive_no_growth = 0
                last_height = new_height
                print(f"    Scroll... {current_links} liens | {new_height}px", flush=True)

            if current_links >= self.max_products:
                break

        links: list[str] = page.evaluate(f"""() => {{
            const links = Array.from(document.querySelectorAll('a'))
                .map(a => a.href)
                .filter(h => h && h.includes('-p') && /-p\\d{{8,}}\\.html/.test(h));
            return [...new Set(links)].slice(0, {self.max_products});
        }}""")

        print(f"    {len(links)} liens collectés", flush=True)
        return links

    # ------------------------------------------------------------------
    # Extraction d'une fiche produit
    # ------------------------------------------------------------------

    def extract_product(
        self, page: Page, link: str, sexe_label: str, genre_category: str
    ) -> Optional[Product]:
        page.goto(link, wait_until="domcontentloaded", timeout=60000)
        time.sleep(random.uniform(2, 4))

        raw = page.evaluate(self._JS_EXTRACT)

        if not raw.get("name"):
            return None

        # Détection type/catégorie/style via URL + fallback sur nom+desc
        url_lower = link.lower()
        full_text = url_lower + " " + (raw["name"] or "").lower() + " " + (raw["desc"] or "").lower()
        type_, categorie, style = self.detect_category(full_text)

        # Zara précise souvent le type dans l'URL
        if "chaussure" in url_lower or "sneaker" in url_lower or "botte" in url_lower:
            type_ = "Chaussures"

        image = raw.get("image")
        if image and image.startswith("//"):
            image = "https:" + image

        return Product(
            name=raw["name"],
            price_value=raw["price"],
            currency="€",
            description=raw["desc"] or "",
            genre=genre_category,
            sexe=sexe_label,
            type=type_,
            categorie=categorie,
            style=style,
            sizes=raw["sizes"],
            color=raw["colors"] if raw["colors"] else None,
            rating=None,  # Zara n'affiche pas de notes
            image=image,
            url=link,
            brand=self.brand,
        )

    # ------------------------------------------------------------------
    # Script JS d'extraction (ld+json schema.org — très fiable sur Zara)
    # ------------------------------------------------------------------

    _JS_EXTRACT = r"""() => {
        let sizes = [], colors = [], price = null, desc = null, name = null, image = null;

        // Extraction via ld+json (schema.org) — source la plus fiable sur Zara
        const scripts = Array.from(document.querySelectorAll('script[type="application/ld+json"]'));
        for (const s of scripts) {
            try {
                const data = JSON.parse(s.innerText);
                const variants = Array.isArray(data) ? data : [data];
                variants.forEach(v => {
                    if (v.color && !colors.includes(v.color.trim())) colors.push(v.color.trim());
                    if (v.size && !sizes.includes(v.size.trim()))   sizes.push(v.size.trim());
                    if (!price) price = v.offers?.price ?? v.offers?.[0]?.price ?? null;
                    if (!desc)  desc  = v.description ?? null;
                    if (!name)  name  = v.name ?? null;
                    if (!image) image = v.image ?? null;
                });
            } catch(e) {}
        }

        // Fallbacks DOM si ld+json incomplet
        if (!name)  name  = document.querySelector('h1')?.innerText.trim() || null;
        if (!desc)  desc  = document.querySelector('.product-detail-description, [class*="description"]')?.innerText.trim() || null;
        if (!image) image = document.querySelector('meta[property="og:image"]')?.content || null;

        // Prix depuis le DOM si absent du ld+json
        if (!price) {
            const priceEl = Array.from(document.querySelectorAll('span, p'))
                .find(el => el.innerText.includes('€') && /\d/.test(el.innerText) && el.innerText.length < 15);
            if (priceEl) {
                price = parseFloat(priceEl.innerText.replace(/[^\d.,]/g, '').replace(',', '.')) || null;
            }
        }

        return {
            name,
            desc,
            price: price ? parseFloat(String(price).replace(',', '.')) : null,
            sizes: [...new Set(sizes)],
            colors: [...new Set(colors)],
            image
        };
    }"""
