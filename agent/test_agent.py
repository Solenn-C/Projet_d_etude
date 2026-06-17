"""Test de l'agent avec les données du db.json."""

import json
from pathlib import Path
from conseil import conseiller

# Charger db.json
DB_PATH = Path(__file__).parent.parent / "db.json"
with open(DB_PATH, encoding="utf-8") as f:
    db = json.load(f)

# Prendre le premier utilisateur
user = db["users"][0]
user_id = user["id"]

wardrobe = db["wardrobe"].get(user_id, {})
profil   = next((p for p in db["profiles"] if p["userId"] == user_id), {})

print(f"Utilisateur : {user['prenom']} {user['nom']}")
print(f"Styles : {profil.get('styles', [])}")
print(f"Pièces : {sum(len(v) for v in wardrobe.values())} vêtements\n")

# Test avec différentes demandes
demandes = [
    "J'ai une soirée au restaurant ce soir, je veux une tenue élégante",
    "Tenue casual pour aller faire des courses demain",
]

for demande in demandes:
    print(f"DEMANDE : {demande}")
    print("-" * 60)
    result = conseiller(wardrobe=wardrobe, profil=profil, demande=demande)

    tenue = result.get("tenue", {})
    for categorie, item in tenue.items():
        if item:
            print(f"  {categorie.upper()} : {item['nom']} ({item.get('couleur', '')})")

    print(f"\n  Style : {result.get('style_tenue', '')}")
    print(f"  Conseil : {result.get('conseil', '')}")
    print()
