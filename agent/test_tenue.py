"""Test de la détection de tenue complète."""

from pathlib import Path
from analyse_tenue import analyser_tenue

# Mettez ici une photo de vous ou d'une tenue complète
# (une photo de profil Instagram, lookbook, etc.)
source = input("Chemin ou URL d'une photo de tenue complète : ").strip()

print("\nAnalyse en cours...")
result = analyser_tenue(source)

print(f"\nStyle global  : {result.get('style_global', '?')}")
print(f"Occasions     : {', '.join(result.get('occasions', []))}")
print(f"\n{len(result['vetements'])} vêtements détectés :")
for v in result["vetements"]:
    marque  = f" — {v['marque']}" if v.get("marque") else ""
    couleur = v.get("couleur") or "?"
    print(f"  • {v['type']:15s} {couleur:20s} {v['saisons']}{marque}")
