# ============================================================
# agent/test_agent.py
# ============================================================
# RÔLE : Script de test manuel de agent.conseil.conseiller() sur
#        les données réelles du premier utilisateur de db.json.
#
# DESCRIPTION :
#   Script à lancer manuellement (pas un test pytest) pour
#   vérifier que conseiller() produit une tenue cohérente à
#   partir de la garde-robe et du profil d'un utilisateur réel,
#   pour plusieurs exemples de demandes.
#
#   ATTENTION (code mort/cassé) :
#   - `DB_PATH` pointe vers <racine_projet>/db.json, alors que la
#     base réelle est Frontend/db.json → FileNotFoundError si exécuté
#     tel quel.
#   - `from conseil import conseiller` est un import relatif qui ne
#     fonctionne que si le script est lancé depuis le dossier agent/
#     (sinon ModuleNotFoundError car agent/ est un package).
#
# FONCTIONS / ENDPOINTS PRINCIPAUX :
#   - (script procédural, pas de fonction) : charge db.json, prend le
#     premier utilisateur et affiche le résultat de conseiller()
#     pour une liste de demandes de test
#
# DÉPENDANCES :
#   - agent.conseil (conseiller)
#   - Frontend/db.json (chemin actuellement incorrect, voir ci-dessus)
#
# APPELS ENTRANTS :
#   - (aucun — script lancé manuellement en local pour debug)
#
# APPELS SORTANTS :
#   - agent.conseil.conseiller() (Groq)
# ============================================================

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
