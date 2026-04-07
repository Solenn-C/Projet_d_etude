import random
import re
import time
from typing import Optional

from playwright.sync_api import Page

import config
from scrapers.base import BaseScraper, Product


class JulesScraper(BaseScraper):
    """Scraper pour Jules (fr-fr, Homme uniquement)."""

    brand = "Jules"
    browser_type = "firefox"

    def get_targets(self) -> list[tuple[str, str, str]]:
        return [
            ("Homme", "https://www.jules.com/fr-fr/l/nouveautes/?sz=288", "Adultes"),
        ]

    # ------------------------------------------------------------------
    # Cookies
    # ------------------------------------------------------------------

    def accept_cookies(self, page: Page) -> None:
        try:
            btn = page.locator(
                '#onetrust-accept-btn-handler, '
                'button:has-text("Tout accepter"), '
                'button:has-text("Accepter tout"), '
                'button:has-text("Accepter"), '
                'button:has-text("Accept all")'
            ).first
            if btn.is_visible(timeout=6000):
                btn.click()
                time.sleep(1)
                print("    ✓ Cookies acceptés", flush=True)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Extraction des liens produits (page déjà complète grâce à ?sz=288)
    # ------------------------------------------------------------------

    def extract_product_links(self, page: Page) -> list[str]:
        # Scroll pour s'assurer que tout est bien chargé
        for _ in range(6):
            page.mouse.wheel(0, 2000)
            time.sleep(0.6)

        links: list[str] = page.evaluate(f"""() => {{
            const anchors = Array.from(document.querySelectorAll('a[href]'));
            const links = anchors
                .map(a => a.href)
                .filter(h =>
                    h.includes('jules.com') &&
                    (h.includes('/p/') || h.match(/\/[a-z0-9-]+-\d{{5,}}\.html/))
                );
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

        try:
            page.wait_for_selector("h1", timeout=15000)
        except Exception:
            return None

        page.mouse.wheel(0, 600)
        time.sleep(3)

        # Scroll pour charger le bloc rating
        page.mouse.wheel(0, 1000)
        time.sleep(1.5)

        raw = page.evaluate(self._JS_EXTRACT)

        if not raw.get("name"):
            return None

        # Nettoyage HTML de la description
        desc = re.sub(r"<[^>]+>", " ", raw.get("desc") or "")
        desc = re.sub(r"\s+", " ", desc).strip()[:500]

        full_text = (raw["name"] + " " + desc).lower()
        type_, categorie, style = self.detect_category(full_text)

        image = raw.get("image")
        if image and image.startswith("//"):
            image = "https:" + image

        time.sleep(random.uniform(1, 2.5))

        return Product(
            name        = raw["name"],
            price_value = raw.get("price"),
            currency    = "€",
            description = desc,
            genre       = genre_category,
            sexe        = sexe_label,
            type        = type_,
            categorie   = categorie,
            style       = style,
            sizes       = raw.get("sizes", []),
            color       = raw.get("colors") or None,
            rating      = raw.get("rating"),
            image       = image,
            url         = link,
            brand       = self.brand,
        )

    # ------------------------------------------------------------------
    # Script JS d'extraction
    # ------------------------------------------------------------------

    _JS_EXTRACT = r"""() => {
        let name = null, desc = null, price = null, sizes = [], colors = [], rating = null, image = null;

        // --- 1. ld+json ---
        const scripts = Array.from(document.querySelectorAll('script[type="application/ld+json"]'));
        for (const s of scripts) {
            try {
                const data = JSON.parse(s.innerText);
                const variants = Array.isArray(data) ? data : [data];
                variants.forEach(function(v) {
                    if (!name  && v.name)        name  = v.name.trim();
                    if (!desc  && v.description) desc  = v.description.trim();
                    if (!image && v.image)        image = Array.isArray(v.image) ? v.image[0] : v.image;
                    if (!price) {
                        var p = (v.offers && v.offers.price) ? v.offers.price : (v.offers && v.offers[0] ? v.offers[0].price : null);
                        if (p) price = parseFloat(String(p).replace(',', '.'));
                    }
                    if (v.color && colors.indexOf(v.color.trim()) === -1) colors.push(v.color.trim());
                    if (v.size  && sizes.indexOf(v.size.trim())   === -1) sizes.push(v.size.trim());
                });
            } catch(e) {}
        }

        // --- 2. Fallbacks DOM ---
        if (!name) { var h1 = document.querySelector('h1'); if (h1) name = h1.innerText.trim(); }
        if (!desc) {
            var descEl = document.querySelector('[class*="description"],[itemprop="description"],#description');
            if (descEl) desc = descEl.innerText.trim() || null;
        }
        if (!image) { var og = document.querySelector('meta[property="og:image"]'); if (og) image = og.content; }

        // --- 3. Prix DOM ---
        if (!price) {
            var allEls = Array.from(document.querySelectorAll('span,div,p'));
            for (var i = 0; i < allEls.length; i++) {
                var el = allEls[i];
                if (el.innerText.indexOf('€') !== -1 && /\d/.test(el.innerText) && el.innerText.length < 15) {
                    var val = parseFloat(el.innerText.replace(/[^\d.,]/g, '').replace(',', '.'));
                    if (!isNaN(val) && val < 1000) { price = val; break; }
                }
            }
        }

        // --- 4. Tailles (uniquement valeurs reconnues) ---
        if (sizes.length === 0) {
            var knownSizes = ["XXS","XS","S","M","L","XL","XXL","XXXL","28","29","30","31","32","33","34","36","38","40","42","44","46","48","50","52","54","56","58","35","37","39","41","43","45"];
            Array.from(document.querySelectorAll('button,span,li,option')).forEach(function(el) {
                var txt = (el.innerText || el.value || '').trim();
                if (knownSizes.indexOf(txt) !== -1 && sizes.indexOf(txt) === -1) sizes.push(txt);
            });
        }

        // --- 5. Couleurs ---
        if (colors.length === 0) {
            var colorEl = document.querySelector('[class*="color-label"],[class*="colorLabel"],[class*="colorName"],[class*="colour-label"]');
            if (colorEl) colors = [colorEl.innerText.trim()];
        }

        // --- 6. Rating ---
        var ratingEl = document.querySelector('#js-zone-global-rating div div span:first-child span');
        if (ratingEl) {
            var rm = ratingEl.innerText.trim().match(/(\d+[.,]\d+)/);
            if (rm) rating = parseFloat(rm[1].replace(',', '.'));
        }

        return { name: name, desc: desc ? desc.substring(0, 500) : null, price: price, sizes: sizes.filter(function(v,i,a){ return a.indexOf(v)===i; }), colors: colors.filter(function(v,i,a){ return a.indexOf(v)===i; }), rating: rating, image: image };
    }"""
