"""
Télécharge toutes les images produits depuis PostgreSQL et les organise
dans un dossier dataset/ structuré par label (style) pour l'entraînement CNN.

Structure de sortie :
    dataset/
        T-shirt/
            img_001.jpg
            img_002.jpg
        Jean/
            img_001.jpg
        Pull/
            ...

Usage :
    python scripts/download_images.py
    python scripts/download_images.py --label style        # défaut
    python scripts/download_images.py --label categorie
    python scripts/download_images.py --label type
    python scripts/download_images.py --min-per-class 10  # ignore classes < 10 images
    python scripts/download_images.py --output data/images
"""

import argparse
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

BASE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
}

# Headers spécifiques par domaine CDN
DOMAIN_HEADERS: dict[str, dict] = {
    "zara.net": {
        "Referer": "https://www.zara.com/",
        "Origin":  "https://www.zara.com",
    },
    "zara.com": {
        "Referer": "https://www.zara.com/",
    },
    "hm.com": {
        "Referer": "https://www2.hm.com/",
    },
    "asos-media.com": {
        "Referer":         "https://www.asos.com/",
        "Origin":          "https://www.asos.com",
        "Sec-Fetch-Dest":  "image",
        "Sec-Fetch-Mode":  "no-cors",
        "Sec-Fetch-Site":  "cross-site",
    },
    "jules.com": {
        "Referer": "https://www.jules.com/",
    },
    "lecoqsportif.com": {
        "Referer": "https://www.lecoqsportif.com/",
    },
}

TIMEOUT = 20       # secondes par requête
DELAY   = 0.4      # pause entre téléchargements (secondes)
MAX_RETRIES = 2    # tentatives en cas d'erreur réseau

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def sanitize(name: str) -> str:
    """Convertit un label en nom de dossier valide."""
    return "".join(c if c.isalnum() or c in " _-" else "_" for c in name).strip()


def get_extension(url: str, content_type: str = "") -> str:
    """Déduit l'extension à partir de l'URL ou du Content-Type."""
    path = urlparse(url).path.lower()
    for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        if path.endswith(ext):
            return ext.replace(".jpeg", ".jpg")
    if "png" in content_type:
        return ".png"
    if "webp" in content_type:
        return ".webp"
    return ".jpg"


def build_headers(url: str) -> dict:
    """Construit les headers HTTP avec les bons headers selon le domaine."""
    headers = dict(BASE_HEADERS)
    for domain, extra in DOMAIN_HEADERS.items():
        if domain in url:
            headers.update(extra)
            break
    return headers


def download_image(url: str, dest: Path) -> tuple[bool, str]:
    """
    Télécharge une image vers dest via requests.
    Retourne (succès, raison_echec).
    """
    headers = build_headers(url)
    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = requests.get(url, headers=headers, timeout=TIMEOUT, stream=True)
            if resp.status_code in (403, 401):
                return False, f"HTTP {resp.status_code}"
            if resp.status_code == 404:
                return False, "HTTP 404"
            if resp.status_code != 200:
                if attempt < MAX_RETRIES:
                    time.sleep(1)
                    continue
                return False, f"HTTP {resp.status_code}"
            content_type = resp.headers.get("Content-Type", "")
            if "text" in content_type or "html" in content_type:
                return False, "réponse HTML (pas une image)"
            dest.write_bytes(resp.content)
            return True, ""
        except requests.exceptions.Timeout:
            if attempt < MAX_RETRIES:
                time.sleep(1)
        except requests.exceptions.RequestException as e:
            return False, str(e)[:60]
    return False, "timeout"


PLAYWRIGHT_DELAY      = 1.0   # délai normal entre images
PLAYWRIGHT_BATCH_SIZE = 30    # renouvelle les cookies tous les N téléchargements
PLAYWRIGHT_BACKOFF    = 8     # pause (s) après un timeout avant de réessayer

WARMUP_URLS = {
    "asos-media": "https://www.asos.com/",
    "hm.com":     "https://www2.hm.com/fr_fr/index.html",
}


def _warmup(context, url: str, page=None):
    """Visite une page pour obtenir/renouveler les cookies."""
    p = page or context.new_page()
    try:
        p.goto(url, wait_until="domcontentloaded", timeout=25000)
        time.sleep(2)
    except Exception:
        pass
    return p


def download_asos_images(rows: list, output_dir: Path, counters: dict) -> tuple[int, int]:
    """
    Télécharge les images ASOS/HM via Playwright (CDN anti-bot).
    Renouvelle les cookies tous les PLAYWRIGHT_BATCH_SIZE images.
    Retourne (ok, errors).
    """
    ok = 0
    errors = 0
    consecutive_timeouts = 0

    with sync_playwright() as p:
        # ASOS/HM utilisent Akamai Bot Manager qui détecte headless → visible obligatoire
        browser = p.chromium.launch(headless=False)

        def make_context():
            ctx = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                )
            )
            pg = ctx.new_page()
            for domain, warmup_url in WARMUP_URLS.items():
                _warmup(ctx, warmup_url, pg)
            return ctx, pg

        context, page = make_context()
        batch_count = 0

        for i, (product_id, label, image_url) in enumerate(rows):
            label_dir = output_dir / sanitize(label)
            label_dir.mkdir(parents=True, exist_ok=True)
            counters[label] = counters.get(label, 0) + 1
            idx = counters[label]
            ext = get_extension(image_url)
            dest = label_dir / f"img_{idx:05d}{ext}"

            if dest.exists():
                continue

            # Renouvellement périodique du contexte (nouveaux cookies)
            if batch_count > 0 and batch_count % PLAYWRIGHT_BATCH_SIZE == 0:
                print(f"  → Renouvellement cookies ({batch_count} images)...", flush=True)
                try:
                    context.close()
                except Exception:
                    pass
                context, page = make_context()
                consecutive_timeouts = 0

            try:
                # Navigation réelle vers l'URL de l'image (fingerprint navigateur complet)
                with page.expect_response(
                    lambda r: r.url.split("?")[0] == image_url.split("?")[0],
                    timeout=25000
                ) as resp_info:
                    page.goto(image_url, wait_until="commit", timeout=25000)

                response = resp_info.value
                if response.ok:
                    dest.write_bytes(response.body())
                    ok += 1
                    batch_count += 1
                    consecutive_timeouts = 0
                    print(f"  ✓ [{label}] img_{idx:05d}{ext}", flush=True)
                else:
                    errors += 1
                    batch_count += 1
                    print(f"  ✗ [{label}] id={product_id} — HTTP {response.status}", flush=True)

            except Exception as e:
                msg = str(e)
                if "Timeout" in msg or "timeout" in msg:
                    consecutive_timeouts += 1
                    print(f"  ⏳ [{label}] id={product_id} — timeout #{consecutive_timeouts}, pause {PLAYWRIGHT_BACKOFF}s...", flush=True)
                    time.sleep(PLAYWRIGHT_BACKOFF)
                    if consecutive_timeouts >= 3:
                        print("  → Renouvellement contexte après timeouts répétés...", flush=True)
                        try:
                            context.close()
                        except Exception:
                            pass
                        context, page = make_context()
                        consecutive_timeouts = 0
                    errors += 1
                else:
                    errors += 1
                    print(f"  ✗ [{label}] id={product_id} — {msg[:80]}", flush=True)

            time.sleep(PLAYWRIGHT_DELAY)

        try:
            context.close()
        except Exception:
            pass
        browser.close()

    return ok, errors


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Télécharge les images produits depuis PostgreSQL")
    parser.add_argument(
        "--label",
        default="style",
        choices=["style", "categorie", "type"],
        help="Colonne utilisée comme label/classe (défaut : style)",
    )
    parser.add_argument(
        "--output",
        default="dataset",
        help="Dossier de sortie (défaut : dataset/)",
    )
    parser.add_argument(
        "--min-per-class",
        type=int,
        default=5,
        dest="min_per_class",
        help="Ignorer les classes avec moins de N images (défaut : 5)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Limite totale de produits (0 = tous)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if not DATABASE_URL:
        print("❌ DATABASE_URL manquant dans .env")
        sys.exit(1)

    engine = create_engine(DATABASE_URL, echo=False)
    output_dir = Path(args.output)

    # --- 1. Récupération depuis PostgreSQL ---
    print(f"Connexion à la base de données...")
    with Session(engine) as session:
        limit_clause = f"LIMIT {args.limit}" if args.limit > 0 else ""
        rows = session.execute(text(f"""
            SELECT id, {args.label}, image
            FROM products
            WHERE image IS NOT NULL
              AND {args.label} IS NOT NULL
              AND {args.label} != ''
            {limit_clause}
        """)).fetchall()

    print(f"  → {len(rows)} produits avec image et label '{args.label}'")

    # --- 2. Comptage par classe ---
    from collections import Counter
    class_counts = Counter(row[1] for row in rows)
    valid_classes = {cls for cls, count in class_counts.items() if count >= args.min_per_class}

    print(f"\nClasses disponibles ({len(valid_classes)} avec ≥ {args.min_per_class} images) :")
    for cls, count in sorted(class_counts.items(), key=lambda x: -x[1]):
        status = "✓" if cls in valid_classes else f"✗ (< {args.min_per_class})"
        print(f"  {status:20s} {cls}: {count} images")

    rows = [r for r in rows if r[1] in valid_classes]
    print(f"\n{len(rows)} images à télécharger")

    if not rows:
        print("Rien à télécharger.")
        return

    # --- 3. Séparation ASOS/HM vs autres (CDN bloque requests) ---
    def needs_playwright(url: str) -> bool:
        return "asos-media" in url or "hm.com" in url

    playwright_rows = [(pid, lbl, url) for pid, lbl, url in rows if needs_playwright(url)]
    other_rows      = [(pid, lbl, url) for pid, lbl, url in rows if not needs_playwright(url)]

    ok = 0
    skipped = 0
    errors = 0
    counters: dict[str, int] = {}

    # --- 3a. Téléchargement classique (Zara, Jules, HM, Le Coq Sportif) ---
    for product_id, label, image_url in other_rows:
        label_dir = output_dir / sanitize(label)
        label_dir.mkdir(parents=True, exist_ok=True)

        counters[label] = counters.get(label, 0) + 1
        idx = counters[label]
        ext = get_extension(image_url)
        dest = label_dir / f"img_{idx:05d}{ext}"

        if dest.exists():
            skipped += 1
            continue  # compteur déjà incrémenté avant le check

        success, reason = download_image(image_url, dest)
        if success:
            ok += 1
            print(f"  ✓ [{label}] img_{idx:05d}{ext}", flush=True)
        else:
            errors += 1
            print(f"  ✗ [{label}] id={product_id} — {reason} ({image_url[:55]}...)", flush=True)

        time.sleep(DELAY)

    # --- 3b. ASOS + HM via Playwright ---
    if playwright_rows:
        print(f"\n→ {len(playwright_rows)} images ASOS/HM via Playwright...")
        asos_ok, asos_err = download_asos_images(playwright_rows, output_dir, counters)
        ok += asos_ok
        errors += asos_err

    # --- 4. Résumé ---
    print(f"\n{'='*50}")
    print(f"Téléchargés : {ok}")
    print(f"Déjà présents (skipped) : {skipped}")
    print(f"Erreurs : {errors}")
    print(f"Dossier de sortie : {output_dir.resolve()}")
    print(f"\nStructure créée :")
    for cls_dir in sorted(output_dir.iterdir()):
        if cls_dir.is_dir():
            n = len(list(cls_dir.glob("*")))
            print(f"  {cls_dir.name}/ → {n} images")


if __name__ == "__main__":
    main()
