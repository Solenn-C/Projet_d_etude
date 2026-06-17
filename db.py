import json
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import (
    ARRAY, Column, Float, Integer, String, Text, create_engine
)
from sqlalchemy.orm import DeclarativeBase, Session

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_engine(DATABASE_URL, echo=False)


# ---------------------------------------------------------------------------
# Schéma
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    pass


class Product(Base):
    __tablename__ = "products"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    name        = Column(String(300), nullable=False)
    brand       = Column(String(100))
    price_value = Column(Float)
    currency    = Column(String(10), default="€")
    description = Column(Text)
    genre       = Column(String(50))   # Adultes | Enfant
    sexe        = Column(String(50))   # Femme | Homme | Fille | Garçon | Unisexe
    type        = Column(String(50))   # Vêtement | Chaussures | Accessoires
    categorie   = Column(String(50))   # Haut | Bas | Ensemble | ...
    style       = Column(String(50))   # Jean | T-shirt | Pull | ...
    style_mode  = Column(String(50))   # Casual chic | Streetwear | Classique | ...
    sizes       = Column(ARRAY(String))
    color       = Column(ARRAY(String))
    rating      = Column(Float)
    image       = Column(Text)
    url         = Column(Text, unique=True)


def init_db() -> None:
    """Crée les tables si elles n'existent pas."""
    Base.metadata.create_all(engine)
    print("✓ Tables créées (ou déjà existantes)")


# ---------------------------------------------------------------------------
# Insertion
# ---------------------------------------------------------------------------

def insert_products(products: list[dict]) -> tuple[int, int]:
    """
    Insère une liste de produits (dicts) en ignorant les doublons (même URL).
    Retourne (nb_insérés, nb_ignorés).
    """
    inserted, skipped = 0, 0
    with Session(engine) as session:
        existing_urls = {row[0] for row in session.query(Product.url).all()}
        for p in products:
            if p.get("Url") in existing_urls:
                skipped += 1
                continue
            session.add(Product(
                name        = p.get("Name"),
                brand       = p.get("Brand"),
                price_value = p.get("price_value"),
                currency    = p.get("Currency", "€"),
                description = p.get("Description"),
                genre       = p.get("Genre"),
                sexe        = p.get("Sexe"),
                type        = p.get("Type"),
                categorie   = p.get("Categorie"),
                style       = p.get("Style"),
                sizes       = p.get("Sizes") or [],
                color       = p.get("Color") or [],
                rating      = p.get("Rating"),
                image       = p.get("Image"),
                url         = p.get("Url"),
            ))
            existing_urls.add(p.get("Url"))
            inserted += 1
        session.commit()
    return inserted, skipped


# ---------------------------------------------------------------------------
# Import depuis un fichier JSON
# ---------------------------------------------------------------------------

def import_json(json_path: str | Path) -> None:
    json_path = Path(json_path)
    with open(json_path, encoding="utf-8") as f:
        products = json.load(f)
    inserted, skipped = insert_products(products)
    print(f"✓ {json_path.name} → {inserted} insérés, {skipped} ignorés (doublons)")


# ---------------------------------------------------------------------------
# Lancement direct : python db.py <fichier.json>
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    init_db()
    if len(sys.argv) > 1:
        for path in sys.argv[1:]:
            import_json(path)
    else:
        print("Usage : python db.py output/zara_complet.json output/asos_complet.json ...")
