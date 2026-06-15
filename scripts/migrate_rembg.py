# ============================================================
# scripts/migrate_rembg.py
# ============================================================
# RÔLE : Script one-shot qui retire le fond de toutes les photos
#        existantes de la garde-robe avec rembg.
#
# DESCRIPTION :
#   Parcourt Frontend/db.json, retrouve sur le disque toutes les
#   photos référencées par les items de la garde-robe et applique
#   rembg.remove() sur chacune.
#
#   Cas .jpg/.jpeg : rembg produit une image RGBA (fond transparent),
#   incompatible avec le JPEG. Ces fichiers sont donc sauvegardés en
#   .png (même nom, nouvelle extension), l'ancien .jpg est supprimé,
#   et db.json est mis à jour pour pointer vers le nouveau fichier
#   .png (sur tous les items qui le référencent).
#
#   Usage :
#       cd <racine du projet>
#       py scripts/migrate_rembg.py
#
# FONCTIONS / ENDPOINTS PRINCIPAUX :
#   - collect_photo_refs(db)  : associe à chaque chemin disque les items qui le référencent
#   - main()                  : applique rembg à chaque photo et met à jour db.json si besoin
#
# DÉPENDANCES :
#   - PIL (Image), rembg (remove)
#   - Frontend/db.json (wardrobe[*][*][*].photo)
#
# APPELS ENTRANTS :
#   - (aucun — script lancé manuellement, migration ponctuelle)
#
# APPELS SORTANTS :
#   - rembg.remove() (traitement local, pas d'appel réseau)
# ============================================================

import json
import os

from PIL import Image
from rembg import remove

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
FRONTEND_DIR = os.path.join(PROJECT_ROOT, "Frontend")
DB_FILE      = os.path.join(FRONTEND_DIR, "db.json")


def collect_photo_refs(db: dict) -> dict[str, list[dict]]:
    """Parcourt db['wardrobe'] et associe à chaque chemin disque la liste des
    items (dicts mutables) qui référencent cette photo via leur clé 'photo'."""
    refs: dict[str, list[dict]] = {}
    wardrobe = db.get("wardrobe", {})
    for categories in wardrobe.values():
        for items in categories.values():
            for item in items:
                photo = item.get("photo")
                if not photo:
                    continue
                rel_path = photo.lstrip("/")  # "/uploads/xxx.jpg" -> "uploads/xxx.jpg"
                full_path = os.path.join(FRONTEND_DIR, *rel_path.split("/"))
                refs.setdefault(full_path, []).append(item)
    return refs


# Charge db.json, applique rembg à chaque photo de la garde-robe et met à jour les chemins .jpg -> .png convertis.
def main():
    with open(DB_FILE, "r", encoding="utf-8") as f:
        db = json.load(f)

    photo_refs = collect_photo_refs(db)

    traitees = 0
    erreurs = 0
    ignorees = 0
    converties = 0
    db_modifie = False

    for path in sorted(photo_refs):
        nom_fichier = os.path.basename(path)

        if not os.path.isfile(path):
            print(f"… {nom_fichier} (fichier introuvable, ignoré)")
            ignorees += 1
            continue

        try:
            input_img = Image.open(path)
            output_img = remove(input_img)

            ext = os.path.splitext(path)[1].lower()
            if ext in (".jpg", ".jpeg"):
                # JPEG ne supporte pas l'alpha (RGBA) -> on bascule en PNG
                new_path = os.path.splitext(path)[0] + ".png"
                output_img.save(new_path)
                os.remove(path)

                old_url = "/" + os.path.relpath(path, FRONTEND_DIR).replace(os.sep, "/")
                new_url = "/" + os.path.relpath(new_path, FRONTEND_DIR).replace(os.sep, "/")
                for item in photo_refs[path]:
                    item["photo"] = new_url
                db_modifie = True
                converties += 1

                print(f"✓ {nom_fichier} -> {os.path.basename(new_path)} (db.json mis à jour : {old_url} -> {new_url})")
            else:
                output_img.save(path)  # écrase l'original
                print(f"✓ {nom_fichier}")

            traitees += 1
        except Exception as e:
            print(f"✗ {nom_fichier} (erreur : {e})")
            erreurs += 1

    if db_modifie:
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(db, f, indent=2, ensure_ascii=False)

    print()
    print(f"Résumé : {traitees} photo(s) traitée(s) ({converties} converties .jpg/.jpeg -> .png), "
          f"{erreurs} erreur(s), {ignorees} ignorée(s).")


if __name__ == "__main__":
    main()
