from playwright.sync_api import sync_playwright
import json
import time
import random


def scrape_zara_total():
    # Configuration des catégories avec affectation du Genre strict
    CATEGORIES = [
        {"url": "https://www.zara.com/fr/fr/homme-tout-l7465.html?v1=2443335", "sexe": "Homme", "genre": "Adultes"},
        {"url": "https://www.zara.com/fr/fr/search?searchTerm=femme&section=WOMAN", "sexe": "Femme",
         "genre": "Adultes"},
        {"url": "https://www.zara.com/fr/fr/enfants-fille-collection-l7289.html?v1=2426193", "sexe": "Fille",
         "genre": "Adolescent"},
        {"url": "https://www.zara.com/fr/fr/kids-boy-collection-l5413.html?v1=2426702", "sexe": "Garçon",
         "genre": "Adolescent"},
        {"url": "https://www.zara.com/fr/fr/kids-babygirl-collection-l5415.html?v1=2422053", "sexe": "Fille",
         "genre": "Enfant"},
        {"url": "https://www.zara.com/fr/fr/kids-babyboy-collection-l5414.html?v1=2422703", "sexe": "Garçon",
         "genre": "Enfant"},
        {"url": "https://www.zara.com/fr/fr/kids-mini-view-all-l6750.html?v1=2428166", "sexe": "Unisexe",
         "genre": "Enfant"},
        {"url": "https://www.zara.com/fr/fr/enfants-accessoires-l3.html?v1=2435086", "sexe": "Enfant",
         "genre": "Enfant"}
    ]

    final_results = []
    output_path = "zara_total_sync_2.json"

    with sync_playwright() as p:
        print("🛠️ Lancement du navigateur...")
        browser = p.firefox.launch(headless=False)
        context = browser.new_context(
            viewport={'width': 1280, 'height': 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0"
        )
        page = context.new_page()

        for cat in CATEGORIES:
            print(f"\n📂 CATEGORIE : {cat['sexe']} | Genre : {cat['genre']}")
            try:
                page.goto(cat['url'], wait_until="networkidle", timeout=90000)
                time.sleep(8)

                # --- LOGIQUE DE SCROLL INFINI (YO-YO) ---
                last_height = page.evaluate("document.body.scrollHeight")
                consecutive_no_growth = 0
                while consecutive_no_growth < 4:
                    for _ in range(5):
                        page.mouse.wheel(0, 2000)
                        time.sleep(0.8)
                    page.mouse.wheel(0, -500)
                    time.sleep(1.5)
                    new_height = page.evaluate("document.body.scrollHeight")
                    if new_height == last_height:
                        consecutive_no_growth += 1
                    else:
                        consecutive_no_growth = 0
                        last_height = new_height
                        print(f"   📏 Scroll... Taille : {new_height}px")

                product_links = page.evaluate(r"""() => {
                    const links = Array.from(document.querySelectorAll('a'))
                        .map(a => a.href)
                        .filter(href => href && href.includes('-p') && href.match(/-p\d{8,}\.html/));
                    return [...new Set(links)];
                }""")

                print(f"🔗 {len(product_links)} produits trouvés.")

                # --- EXTRACTION ---
                for i, link in enumerate(product_links, 1):
                    try:
                        page.goto(link, wait_until="domcontentloaded", timeout=60000)

                        product_data = page.evaluate(r"""() => {
                            const getTxt = (sel) => document.querySelector(sel)?.innerText.trim() || null;
                            let sizes = new Set(), colors = new Set(), price = null, desc = null;

                            const ldJson = document.querySelector('script[type="application/ld+json"]');
                            if (ldJson) {
                                try {
                                    const json = JSON.parse(ldJson.innerText);
                                    const variants = Array.isArray(json) ? json : [json];
                                    variants.forEach(v => {
                                        if (v.color) colors.add(v.color.trim());
                                        if (v.size) sizes.add(v.size.trim());
                                        if (!price) price = v.offers?.price || v.offers?.[0]?.price;
                                        if (!desc) desc = v.description;
                                    });
                                } catch(e) {}
                            }

                            const url = window.location.href.toLowerCase();

                            // Détection Style
                            let style = null;
                            if (url.includes('jean')) style = "Jean";
                            else if (url.includes('pantalon')) style = "Pantalon";
                            else if (url.includes('pull') || url.includes('maille')) style = "Pull";
                            else if (url.includes('t-shirt')) style = "T-shirt";
                            else if (url.includes('crop-top')) style = "Crop-top";
                            else if (url.includes('robe')) style = "Robe";
                            else if (url.includes('veste') || url.includes('blouson')) style = "Veste";
                            else if (url.includes('chemise')) style = "Chemise";
                            else if (url.includes('short')) style = "Short";

                            // Détection Catégorie (Haut / Bas)
                            let categorie = null;
                            const bas_keywords = ['pantalon', 'short', 'bermuda', 'jean', 'jupe', 'legging'];
                            const haut_keywords = ['t-shirt', 'pull', 'veste', 'chemise', 'top', 'sweat', 'blouson', 'crop-top', 'cardigan'];

                            if (bas_keywords.some(k => url.includes(k))) categorie = "Bas";
                            else if (haut_keywords.some(k => url.includes(k)) || url.includes('robe')) categorie = "Haut";

                            return {
                                "Name": document.querySelector('h1')?.innerText.trim() || null,
                                "price_value": price ? parseFloat(price) : null,
                                "Currency": "EUR",
                                "Description": desc || getTxt('.product-detail-description'),
                                "Genre": null,         // Rempli par Python
                                "Age": null,
                                "Categorie_Age": null,
                                "Sexe": null,          // Rempli par Python
                                "Color": Array.from(colors).join(', ') || null,
                                "Rating": null,
                                "Type": url.includes('chaussures') ? "Chaussures" : "Vêtement",
                                "Catégorie": categorie,
                                "Style": style,
                                "Image": document.querySelector('meta[property="og:image"]')?.content || null,
                                "Url": url,
                                "Saison": null,
                                "Sizes": Array.from(sizes)
                            };
                        }""")

                        if product_data["Name"]:
                            product_data["Sexe"] = cat["sexe"]
                            product_data["Genre"] = cat["genre"]  # Adultes, Adolescent ou Enfant

                            final_results.append(product_data)

                            if i % 10 == 0:
                                with open(output_path, "w", encoding="utf-8") as f:
                                    json.dump(final_results, f, indent=4, ensure_ascii=False)
                                print(f"   ✅ {cat['sexe']} : {i}/{len(product_links)}")

                    except Exception:
                        continue
                    time.sleep(random.uniform(0.3, 0.6))

            except Exception as e:
                print(f"❌ Erreur {cat['sexe']} : {e}")

        browser.close()

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(final_results, f, indent=4, ensure_ascii=False)
    print(f"\n✨ Terminé ! Total : {len(final_results)} produits.")


if __name__ == "__main__":
    scrape_zara_total()
