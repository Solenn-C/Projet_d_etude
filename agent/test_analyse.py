"""Test de l'analyse d'image avec des images locales du dataset."""

from pathlib import Path
from analyse_image import analyser_image

# Images locales du dataset
images = [
    ("Robe",         Path("../dataset/Robe/img_00001.jpg")),
    ("Jean",         Path("../dataset/Jean/img_00001.jpg")),
    ("T-shirt",      Path("../dataset/T-shirt/img_00001.jpg")),
    ("Veste_Manteau",Path("../dataset/Veste_Manteau/img_00001.jpg")),
]

for label, path in images:
    print(f"[{label}] {path.name}")
    try:
        result = analyser_image(path, type_vetement=label)
        print(f"  Couleur     : {result['couleur']}")
        print(f"  Secondaires : {result['couleurs_secondaires']}")
        print(f"  Saisons     : {result['saisons']}")
        print(f"  Marque      : {result['marque']} ({result['confidence_marque']})")
    except Exception as e:
        print(f"  Erreur : {e}")
    print()
