import time
from typing import Optional

from playwright.sync_api import Page

import config
from scrapers.base import BaseScraper, Product


class HMScraper(BaseScraper):
    """Scraper pour H&M (fr_fr)."""

    brand = "H&M"

    def get_targets(self) -> list[tuple[str, str, str]]:
        return [
            ("Femme",  "https://www2.hm.com/fr_fr/femme/catalogue-par-produit/view-all.html",  "Adultes"),
            ("Homme",  "https://www2.hm.com/fr_fr/homme/catalogue-par-produit/view-all.html",  "Adultes"),
            ("Enfant", "https://www2.hm.com/fr_fr/enfant/catalogue-par-produit/view-all.html", "Enfant"),
        ]

    def accept_cookies(self, page: Page) -> None:
        """Ferme la popup cookies H&M si elle est présente."""
        try:
            btn = page.locator(
                '#onetrust-accept-btn-handler, '
                'button:has-text("Accepter tous les cookies"), '
                'button:has-text("Accepter tout"), '
                'button:has-text("Tout accepter"), '
                'button:has-text("Accept all")'
            ).first
            if btn.is_visible(timeout=5000):
                btn.click()
                time.sleep(1)
                print("    ✓ Cookies acceptés", flush=True)
        except Exception:
            pass

    def extract_product_links(self, page: Page) -> list[str]:
        """Collecte les liens page par page en cliquant sur 'Charger la page suivante'."""
        all_links: list[str] = []

        while len(all_links) < self.max_products:
            # Récupère les liens de la page courante
            page_links: list[str] = page.evaluate("""() =>
                Array.from(document.querySelectorAll('a[href*="/productpage."]'))
                    .map(a => a.href)
            """)
            # Ajoute uniquement les nouveaux liens
            for link in page_links:
                if link not in all_links:
                    all_links.append(link)

            print(f"    {len(all_links)} liens collectés...", flush=True)

            if len(all_links) >= self.max_products:
                break

            # Cherche et clique sur le bouton de pagination
            try:
                btn = page.locator(
                    'button:has-text("Charger la page suivante"), '
                    'button:has-text("Load more"), '
                    'button:has-text("Voir plus"), '
                    'a:has-text("Charger la page suivante")'
                ).first
                if btn.is_visible(timeout=3000):
                    btn.scroll_into_view_if_needed()
                    btn.click()
                    time.sleep(4)  # attend le chargement de la nouvelle page
                else:
                    print(f"    Fin du catalogue ({len(all_links)} liens)", flush=True)
                    break
            except Exception:
                print(f"    Fin du catalogue ({len(all_links)} liens)", flush=True)
                break

        return all_links[:self.max_products]

    def extract_product(
        self, page: Page, link: str, sexe_label: str, genre_category: str
    ) -> Optional[Product]:
        page.goto(link, wait_until="domcontentloaded", timeout=60000)
        time.sleep(config.PRODUCT_LOAD_WAIT)

        # Ouvrir le sélecteur de taille
        try:
            size_button = page.locator(
                'button[id*="size-picker"], .picker-common button, #picker-1'
            ).first
            if size_button.is_visible():
                size_button.click()
                time.sleep(2)
        except Exception:
            pass

        # Déplier la description
        try:
            page.evaluate("window.scrollBy(0, 400)")
            page.locator(
                '#toggle-descriptionAccordion, button:has-text("DESCRIPTION")'
            ).first.click(timeout=2000)
            time.sleep(1)
        except Exception:
            pass

        # Scroller pour déclencher le lazy load des avis (Bazaarvoice)
        try:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(2)
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(1)
        except Exception:
            pass

        raw = page.evaluate(self._JS_EXTRACT)

        full_text = (raw["name"] + " " + raw["desc"]).lower()
        type_, categorie, style = self.detect_category(full_text)

        if sexe_label == "Enfant":
            final_sexe = raw["detected_sexe"] if raw["detected_sexe"] else "Unisexe"
        else:
            final_sexe = sexe_label

        image = raw["image"]
        if image and image.startswith("//"):
            image = "https:" + image

        return Product(
            name=raw["name"],
            price_value=raw["price"],
            currency="€",
            description=raw["desc"],
            genre=genre_category,
            sexe=final_sexe,
            type=type_,
            categorie=categorie,
            style=style,
            sizes=raw["sizes"],
            color=raw["colors"] if raw["colors"] else None,
            rating=raw["rating"],
            image=image,
            url=link,
            brand=self.brand,
        )

    _JS_EXTRACT = r"""() => {
        // --- Nom ---
        const name = document.querySelector('h1')?.innerText.trim() || "";

        // --- Description ---
        const descElem = document.querySelector('#section-descriptionAccordion p')
                      || document.querySelector('.pdp-description-text');
        const desc = (descElem?.innerText.trim() || "").split("Référence")[0].trim();

        // --- Tailles ---
        const sizeTags = [
            "XXS","XS","S","M","L","XL","XXL",
            "32","34","36","38","40","42","44","46","48",
            "50","50/56","56","62","62/68","68","74","74/80","80",
            "86","86/92","92","98","98/104","104","110","110/116",
            "116","122","122/128","128","134","134/140","140",
            "146","146/152","152","158","158/164","164","170",
            "15","16","17","18","19","20","21","22","23","24","25",
            "26","27","28","29","30","31","32","33","34","35",
            "36","37","38","39","40","41","42","43","44","45"
        ];
        const rawEls = Array.from(document.querySelectorAll(
            '.picker-option, button, span, label, li'
        ));
        const found = [];
        rawEls.forEach(el => {
            let txt = el.innerText.split('(')[0].trim();
            if (sizeTags.includes(txt)) { found.push(txt); return; }
            let aria = (el.getAttribute('aria-label') || "").split(',')[0].trim();
            if (sizeTags.includes(aria)) found.push(aria);
        });

        // --- Prix ---
        let price = null;
        const priceElem = Array.from(document.querySelectorAll('span, div, p'))
            .find(el => el.innerText.includes('€') && /\d/.test(el.innerText) && el.innerText.length < 20);
        if (priceElem) {
            const raw = priceElem.innerText.split('€')[0].replace(/[^\d.,]/g, '').replace(',', '.');
            price = parseFloat(raw) || null;
        }

        // --- Couleurs disponibles ---
        let colors = [];

        // 1. Liens vers variantes de couleur du même produit
        const baseId = window.location.pathname.match(/productpage\.(\d+)/)?.[1]?.slice(0, 7);
        if (baseId) {
            const colorLinks = Array.from(document.querySelectorAll(`a[href*="productpage.${baseId}"]`));
            const fromLinks = colorLinks
                .map(a =>
                    a.getAttribute('aria-label') ||
                    a.getAttribute('title') ||
                    a.querySelector('img')?.getAttribute('alt') || ''
                )
                .map(c => c.trim())
                .filter(c => c.length > 0 && !/voir|view|all/i.test(c));
            if (fromLinks.length > 0) colors = fromLinks;
        }

        // 2. Swatches avec title dans un picker couleur
        if (colors.length === 0) {
            const swatches = Array.from(document.querySelectorAll(
                '[class*="picker"] li[title], [class*="picker"] button[title], ' +
                '[class*="swatch"] [title], [class*="Swatch"] [title]'
            ));
            const fromSwatches = swatches
                .map(el => el.getAttribute('title') || el.getAttribute('aria-label') || '')
                .map(c => c.trim()).filter(c => c.length > 0);
            if (fromSwatches.length > 0) colors = fromSwatches;
        }

        // 3. Couleur affichée en texte (ex: "Couleur : Blanc")
        if (colors.length === 0) {
            for (const el of document.querySelectorAll('p, span, dd, li')) {
                const txt = el.innerText.trim();
                if (/^couleur\s*[:\-]/i.test(txt) && el.children.length === 0) {
                    const c = txt.replace(/^couleur\s*[:\-]\s*/i, '').trim();
                    if (c) { colors = [c]; break; }
                }
            }
        }

        // 4. Fallback meta description
        if (colors.length === 0) {
            const metaDesc = document.querySelector('meta[name="description"]')?.content || '';
            const match = metaDesc.match(/couleur[:\s]+([^,.]+)/i);
            if (match) colors = [match[1].trim()];
        }

        const dedupedColors = [...new Set(colors)];

        // --- Note / Rating (Bazaarvoice) ---
        let rating = null;

        if (!rating) {
            for (const el of document.querySelectorAll('[aria-label*=" out of 5"], [aria-label*="sur 5"], [aria-label*="/5"]')) {
                const match = (el.getAttribute('aria-label') || '').match(/(\d[.,]\d+|\d)/);
                if (match) { rating = parseFloat(match[1].replace(',', '.')); break; }
            }
        }
        if (!rating) {
            const schemaEl = document.querySelector('[itemprop="ratingValue"]');
            if (schemaEl) rating = parseFloat(schemaEl.getAttribute('content') || schemaEl.innerText) || null;
        }
        if (!rating) {
            const bvEl = document.querySelector(
                '.bv_averageRating_component_container, [class*="bv_rating"], [class*="BVRRRatingNumber"]'
            );
            if (bvEl) rating = parseFloat(bvEl.innerText.replace(',', '.')) || null;
        }
        if (!rating) {
            for (const el of document.querySelectorAll('[class*="rating"], [class*="Rating"], [class*="review"], [class*="Review"]')) {
                if (el.children.length > 3) continue;
                const match = el.innerText.match(/^(\d[.,]\d)/);
                if (match) { rating = parseFloat(match[1].replace(',', '.')); break; }
            }
        }

        // --- Sexe enfant ---
        let detectedSexe = "";
        const navText = (document.querySelector('nav[aria-label="Breadcrumb"]')?.innerText || "").toUpperCase();
        if      (navText.includes("FILLE"))                                detectedSexe = "Fille";
        else if (navText.includes("GARÇON") || navText.includes("GARCON")) detectedSexe = "Garçon";
        else if (navText.includes("BÉBÉ")   || navText.includes("BEBE"))   detectedSexe = "Unisexe";

        return {
            name, desc, price,
            sizes: [...new Set(found)],
            colors: dedupedColors,
            rating,
            detected_sexe: detectedSexe,
            image: document.querySelector('meta[property="og:image"]')?.content || null
        };
    }"""
