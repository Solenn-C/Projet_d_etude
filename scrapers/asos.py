import random
import re
import time
from typing import Optional

from playwright.sync_api import Page

import config
from scrapers.base import BaseScraper, Product


class AsosScraper(BaseScraper):
    """Scraper pour ASOS (fr, adultes)."""

    brand = "ASOS"
    browser_type = "chromium"  # ASOS fonctionne mieux avec Chromium

    def get_targets(self) -> list[tuple[str, str, str]]:
        return [
            ("Femme", "https://www.asos.com/fr/femme/nouveau/cat/?cid=27108", "Adultes"),
            ("Homme", "https://www.asos.com/fr/homme/nouveau/cat/?cid=27110", "Adultes"),
        ]

    # ------------------------------------------------------------------
    # Cookies
    # ------------------------------------------------------------------

    def accept_cookies(self, page: Page) -> None:
        try:
            btn = page.locator(
                'button:has-text("Accepter"), button:has-text("Accept"), '
                '#onetrust-accept-btn-handler, [data-testid="close-button"]'
            ).first
            if btn.is_visible(timeout=5000):
                btn.click()
                time.sleep(1)
                print("    ✓ Cookies acceptés", flush=True)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Extraction des liens produits (scroll infini)
    # ------------------------------------------------------------------

    def extract_product_links(self, page: Page) -> list[str]:
        """Scroll infini pour charger les produits ASOS."""
        last_count = 0
        no_growth = 0

        while no_growth < 3:
            for _ in range(4):
                page.mouse.wheel(0, 2000)
                time.sleep(0.8)

            current_count: int = page.evaluate("""() =>
                new Set(Array.from(document.querySelectorAll('a[href*="/prd/"]'))
                    .map(a => a.href)).size
            """)
            print(f"    {current_count} liens chargés...", flush=True)

            if current_count >= self.max_products:
                break
            if current_count == last_count:
                no_growth += 1
            else:
                no_growth = 0
                last_count = current_count

        links: list[str] = page.evaluate(f"""() => {{
            const links = Array.from(document.querySelectorAll('a[href*="/prd/"]'))
                .map(a => a.href);
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

        # Attendre le titre et scroller pour déclencher le chargement des tailles
        try:
            page.wait_for_selector("h1", timeout=15000)
        except Exception:
            return None

        page.mouse.wheel(0, 800)
        time.sleep(4)

        raw = page.evaluate(self._JS_EXTRACT)

        if not raw.get("name"):
            return None

        # --- Nom : retirer la marque si elle est en préfixe ---
        name = raw["name"]
        product_brand = raw.get("brand") or self.brand
        if product_brand and name.lower().startswith(product_brand.lower()):
            name = name[len(product_brand):].strip(" -–|")

        # --- Prix depuis le fullText si absent ---
        price = raw.get("price")
        if not price:
            price_match = re.search(r"(\d+[,.]\d+)\s*€", raw.get("full_text", ""))
            if price_match:
                val = float(price_match.group(1).replace(",", "."))
                price = val if val < 500 else None

        # --- Couleur ---
        color = raw.get("colors") or []
        if not color:
            color_match = re.search(
                r"couleur\s*[:\-]\s*([^\n\r,]{2,40})", raw.get("full_text", ""), re.IGNORECASE
            )
            if color_match:
                color = [color_match.group(1).strip()]

        # --- Description ---
        desc = raw.get("desc") or ""

        # --- Type / Catégorie / Style ---
        full_text = (name + " " + desc).lower()
        type_, categorie, style = self.detect_category(full_text)

        image = raw.get("image")
        if image and image.startswith("//"):
            image = "https:" + image

        time.sleep(random.uniform(1, 2.5))

        return Product(
            name=name,
            price_value=price,
            currency="€",
            description=desc[:500],
            genre=genre_category,
            sexe=sexe_label,
            type=type_,
            categorie=categorie,
            style=style,
            sizes=raw.get("sizes", []),
            color=color if color else None,
            rating=None,
            image=image,
            url=link,
            brand=raw.get("brand") or self.brand,
        )

    # ------------------------------------------------------------------
    # Script JS d'extraction
    # ------------------------------------------------------------------

    _JS_EXTRACT = r"""() => {
        // --- Nom ---
        const name = document.querySelector('h1')?.innerText.trim() || null;

        // --- Description via ld+json (source la plus fiable) ---
        let desc = "";
        const ldScripts = Array.from(document.querySelectorAll('script[type="application/ld+json"]'));
        for (const s of ldScripts) {
            try {
                const data = JSON.parse(s.innerText);
                const variants = Array.isArray(data) ? data : [data];
                for (const v of variants) {
                    if (v.description && v.description.length > 20) {
                        desc = v.description.trim();
                        break;
                    }
                }
            } catch(e) {}
            if (desc) break;
        }

        // --- Tailles ---
        let sizes = [];

        // 1. Via <select> (menu déroulant)
        const allSelects = Array.from(document.querySelectorAll('select'));
        if (allSelects.length > 0) {
            const mainSelect = allSelects.reduce((a, b) =>
                a.options.length > b.options.length ? a : b
            );
            sizes = Array.from(mainSelect.options)
                .map(o => o.text.trim())
                .filter(s => s && !/choisir|guide|panier|épuisé|sélectionner|select/i.test(s))
                .map(s => s.replace(/^(EU|US|UK)\s+/i, '').split(' - ')[0].split(' (')[0].trim())
                .filter(Boolean);
        }

        // 2. Via boutons de taille si le select est vide
        if (sizes.length === 0) {
            sizes = Array.from(document.querySelectorAll(
                '[data-testid*="size"] button, [class*="sizeBtn"], [class*="size-btn"], ' +
                'button[class*="Size"], [aria-label*="Taille"]'
            ))
            .map(el => el.innerText.trim() || el.getAttribute('aria-label') || '')
            .filter(s => s && !/épuisé|unavailable/i.test(s));
        }

        // --- Prix ---
        let price = null;
        const ldJson = document.querySelector('script[type="application/ld+json"]');
        if (ldJson) {
            try {
                const data = JSON.parse(ldJson.innerText);
                const variants = Array.isArray(data) ? data : [data];
                for (const v of variants) {
                    const p = v.offers?.price ?? v.offers?.[0]?.price;
                    if (p) { price = parseFloat(String(p).replace(',', '.')); break; }
                }
            } catch(e) {}
        }

        // --- Couleurs ---
        let colors = [];
        const colorEl = document.querySelector(
            '[data-testid="colour-label"], [class*="colour-label"], ' +
            '[class*="colorName"], [class*="ColourName"]'
        );
        if (colorEl) colors = [colorEl.innerText.trim()];

        // --- Marque réelle du produit ---
        let brand = null;

        // 1. ld+json brand.name
        if (ldJson) {
            try {
                const data = JSON.parse(ldJson.innerText);
                const variants = Array.isArray(data) ? data : [data];
                for (const v of variants) {
                    if (v.brand?.name) { brand = v.brand.name.trim(); break; }
                }
            } catch(e) {}
        }

        // 2. Élément dédié à la marque sur la page
        if (!brand) {
            const brandEl = document.querySelector(
                '[data-testid="product-brand"], [class*="brandName"], ' +
                '[class*="brand-name"], a[href*="/brand/"]'
            );
            if (brandEl) brand = brandEl.innerText.trim() || null;
        }

        // 3. Fallback : balise meta
        if (!brand) {
            brand = document.querySelector('meta[property="product:brand"]')?.content || null;
        }

        // --- Image ---
        let image = document.querySelector('meta[property="og:image"]')?.content || null;
        if (!image) {
            const imgSelectors = [
                '#product-main-image img', 'img[class*="mainImage"]',
                '.gallery-image img', 'img[data-testid="product-main-image"]'
            ];
            for (const sel of imgSelectors) {
                const el = document.querySelector(sel);
                if (el?.src && !el.src.includes('placeholder')) { image = el.src; break; }
            }
        }

        return {
            name,
            desc,
            price,
            sizes: [...new Set(sizes)],
            colors: [...new Set(colors)],
            brand,
            image,
            full_text: document.body.innerText
        };
    }"""
