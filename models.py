from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class Product:
    name: str
    price_value: Optional[float]
    currency: str
    description: str
    genre: str       # "Adultes" | "Enfant"
    sexe: str        # "Femme" | "Homme" | "Enfant" | "Fille" | "Garçon"
    type: str        # "Vêtement" | "Chaussures" | "Accessoires"
    categorie: str   # "Haut" | "Bas" | "Haut/Bas" | "Accessoires"
    style: str       # "Jean" | "T-shirt" | "Pull" | ...
    sizes: List[str] = field(default_factory=list)
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
            "Image": self.image,
            "Url": self.url,
            "Brand": self.brand,
        }
