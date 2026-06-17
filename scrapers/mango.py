import time
from typing import Optional

from playwright.sync_api import Page

import config
from scrapers.base import BaseScraper, Product


class MangoScraper(BaseScraper):
    """
    Scraper pour Mango (fr).
    Ciblé sur les jupes femme pour enrichir le dataset.
    Utilise Chromium (meilleure compatibilité avec le site Mango).
    """

    brand = "Mango"
    browser_type = "chromium"

    def get_targets(self) -> list[tuple[str, str, str]]:
        return [
            # Robes et tops (objectif principal — améliorer les prédictions)
            ("Femme", "https://shop.mango.com/fr/fr/c/femme/robes-et-combinaisons/robes/b4864b2e", "Adultes"),
            ("Femme", "https://shop.mango.com/fr/fr/c/femme/top/227371cd",  "Adultes"),
            # Jupes
            ("Femme", "https://shop.mango.com/fr/fr/c/femme/jupe/a1a0d939", "Adultes"),
        ]

    # ------------------------------------------------------------------
    # Cookies
    # ------------------------------------------------------------------

    def accept_cookies(self, page: Page) -> None:
        try:
            btn = page.locator(
                'button:has-text("Tout accepter"), '
                'button:has-text("Accepter tout"), '
                'button:has-text("Accept all"), '
                '#onetrust-accept-btn-handler'
            ).first
            if btn.is_visible(timeout=6000):
                btn.click()
                time.sleep(1)
                print("    ✓ Cookies acceptés", flush=True)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Extraction des liens produits (scroll infini)
    # ------------------------------------------------------------------

    def extract_product_links(self, page: Page) -> list[str]:
        """Scroll jusqu'au bas de la page catalogue Mango (infinite scroll)."""
        last_count = 0
        no_growth = 0

        while no_growth < 4:
            for _ in range(4):
                page.mouse.wheel(0, 2000)
                time.sleep(0.9)

            count: int = page.evaluate("""() =>
                new Set(
                    Array.from(document.querySelectorAll('a[href*="mango.com"]'))
                        .map(a => a.href)
                        .filter(h => /mango\\.com\\/fr\\/fr\\/p\\//.test(h))
                ).size
            """)

            print(f"    Scroll... {count} liens", flush=True)

            if count == last_count:
                no_growth += 1
            else:
                no_growth = 0
                last_count = count

            if count >= self.max_products:
                break

        links: list[str] = page.evaluate(f"""() => {{
            const links = Array.from(document.querySelectorAll('a[href*="mango.com"]'))
                .map(a => a.href)
                .filter(h => /mango\\.com\\/fr\\/fr\\/p\\//.test(h));
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
        time.sleep(2)

        raw = page.evaluate(self._JS_EXTRACT)

        if not raw.get("name"):
            return None

        # Style forcé selon la catégorie de l'URL, détection auto sinon
        link_l = link.lower()
        if "/jupe/" in link_l:
            type_, categorie, style = "Vêtement", "Bas",      "Jupe"
        elif "/robe/" in link_l:
            type_, categorie, style = "Vêtement", "Ensemble", "Robe"
        elif "/top/" in link_l:
            type_, categorie, style = "Vêtement", "Haut",     "Top"
        else:
            full_text = link_l + " " + (raw["name"] or "").lower() + " " + (raw["desc"] or "").lower()
            type_, categorie, style = self.detect_category(full_text)

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
            rating=None,
            image=raw["image"],
            url=link,
            brand=self.brand,
        )

    # ------------------------------------------------------------------
    # Extraction JS
    # ------------------------------------------------------------------

    _JS_EXTRACT = r"""() => {
        let name = null, desc = null, price = null, sizes = [], colors = [], image = null;

        // 1. ld+json (schema.org) — source la plus fiable
        const scripts = Array.from(document.querySelectorAll('script[type="application/ld+json"]'));
        for (const s of scripts) {
            try {
                const data = JSON.parse(s.innerText);
                const items = Array.isArray(data) ? data : [data];
                for (const item of items) {
                    if (!name)  name  = item.name ?? null;
                    if (!desc)  desc  = item.description ?? null;
                    if (!image) image = Array.isArray(item.image) ? item.image[0] : item.image ?? null;
                    if (!price) price = item.offers?.price
                                     ?? item.offers?.[0]?.price
                                     ?? null;
                    // Variantes (couleurs / tailles)
                    const variants = item.hasVariant ?? item.offers ?? [];
                    for (const v of (Array.isArray(variants) ? variants : [variants])) {
                        if (v.color && !colors.includes(v.color)) colors.push(v.color.trim());
                        if (v.size  && !sizes.includes(v.size))   sizes.push(v.size.trim());
                    }
                }
            } catch(e) {}
        }

        // 2. Fallbacks DOM
        if (!name)  name  = document.querySelector('h1')?.innerText.trim() || null;
        if (!desc)  desc  = document.querySelector('[class*="description"], [class*="product-info"]')
                                     ?.innerText.trim() || null;
        if (!image) image = document.querySelector('meta[property="og:image"]')?.content || null;

        // 3. Prix DOM si absent
        if (!price) {
            const el = Array.from(document.querySelectorAll('span, p'))
                .find(e => /\d+[.,]\d+\s*€/.test(e.innerText) && e.innerText.length < 15);
            if (el) price = parseFloat(el.innerText.replace(/[^\d.,]/g, '').replace(',', '.')) || null;
        }

        // 4. Tailles depuis les boutons de sélection
        if (sizes.length === 0) {
            sizes = Array.from(document.querySelectorAll(
                '[class*="size"] button, [class*="sizeSelector"] span, [data-testid*="size"]'
            )).map(el => el.innerText.trim()).filter(s => s.length > 0 && s.length < 10);
        }

        // 5. Couleurs depuis les swatches Mango
        if (colors.length === 0) {
            // Classe identifiée par inspection DOM : ColorsSelector-module__*__label
            const colorEls = Array.from(document.querySelectorAll('[class*="ColorsSelector"][class*="label"]'));
            for (const el of colorEls) {
                const txt = el.innerText.trim();
                if (txt && txt.length < 40 && !colors.includes(txt)) colors.push(txt);
            }
        }

        // 6. Fallback : meta product:color
        if (colors.length === 0) {
            const colorMeta = document.querySelector('meta[property="product:color"]');
            if (colorMeta) colors.push(colorMeta.content.trim());
        }

        return {
            name,
            desc,
            price: price ? parseFloat(String(price).replace(',', '.')) : null,
            sizes: [...new Set(sizes)],
            colors: [...new Set(colors)],
            image,
        };
    }"""
