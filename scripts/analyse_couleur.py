# ============================================================
# scripts/analyse_couleur.py
# ============================================================
# RÔLE : Wrapper CLI qui appelle l'analyse Groq Vision d'une image
#        de vêtement et affiche le résultat en JSON sur stdout.
#
# DESCRIPTION :
#   Script exécuté en sous-processus (execFile('py', ...)) par
#   server.js, sur le même principe que predict.py pour l'ONNX.
#   Il prend en argument le chemin d'une image (et optionnellement
#   le type de vêtement) et délègue l'analyse à
#   agent.analyse_image.analyser_image.
#
#   Usage :
#       python scripts/analyse_couleur.py <chemin_image> [--type <type_vetement>]
#
#   Sortie stdout (JSON) :
#       {couleur, couleurs_secondaires, saisons, marque, confidence_marque}
#
# FONCTIONS / ENDPOINTS PRINCIPAUX :
#   - main()  : parse les arguments CLI, appelle analyser_image() et
#               affiche le résultat en JSON
#
# DÉPENDANCES :
#   - agent.analyse_image (analyser_image)
#
# APPELS ENTRANTS :
#   - server.js (route /api/analyze-image, via child_process.execFile)
#
# APPELS SORTANTS :
#   - agent.analyse_image.analyser_image() (Groq Vision)
# ============================================================

import argparse
import json
import sys
from pathlib import Path

# Le script est exécuté avec cwd = racine du projet, mais Python place le dossier
# du script (scripts/) en tête de sys.path : on ajoute la racine pour pouvoir
# importer le package agent/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.analyse_image import analyser_image


# Lit les arguments CLI, lance l'analyse de l'image et imprime le résultat JSON.
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("image_path")
    parser.add_argument("--type", dest="type_vetement", default=None)
    args = parser.parse_args()

    result = analyser_image(args.image_path, type_vetement=args.type_vetement)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
