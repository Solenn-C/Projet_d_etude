# ============================================================
# scripts/conseil_tenue.py
# ============================================================
# RÔLE : Wrapper CLI qui appelle agent.conseil.conseiller pour
#        générer une tenue et l'affiche en JSON sur stdout.
#
# DESCRIPTION :
#   Script exécuté en sous-processus (execFile('py', ...)) par
#   server.js, sur le même principe que scripts/analyse_couleur.py.
#
#   Usage :
#       echo {"userId": "...", "demande": "..."} | python scripts/conseil_tenue.py
#
#   Lit un objet JSON sur stdin : {userId, demande, recent?}
#   (stdin plutôt que des arguments : la "demande" est un texte libre,
#   potentiellement long et accentué — passer par stdin/JSON évite toute
#   limite ou souci d'échappement de la ligne de commande.)
#
#   Le champ optionnel "recent" permet de passer explicitement les hauts
#   portés récemment (recent_items de agent.conseil.conseiller) : soit un
#   tableau JSON de noms (["Nom 1", "Nom 2"]), soit une chaîne
#   "Nom 1|Nom 2". Si absent ou vide, conseiller() calcule recent_items
#   lui-même à partir de la garde-robe.
#
#   Sortie stdout (JSON) :
#     - succès : {tenue, style_tenue, conseil, occasion}
#     - erreur  : {error: "...", code?: "WARDROBE_NOT_FOUND"}
#
# FONCTIONS / ENDPOINTS PRINCIPAUX :
#   - fail(message, code)   : imprime un objet JSON d'erreur sur stdout
#   - _parse_recent(value)  : normalise le champ optionnel "recent" en liste de noms
#   - main()                : lit stdin, charge la garde-robe et appelle conseiller()
#
# DÉPENDANCES :
#   - agent.conseil (conseiller)
#   - Frontend/db.json (wardrobe, profiles)
#
# APPELS ENTRANTS :
#   - server.js (route /api/agent/conseil, via child_process.execFile)
#
# APPELS SORTANTS :
#   - agent.conseil.conseiller() (Groq)
# ============================================================

import json
import sys
from pathlib import Path

# Le script est exécuté avec cwd = racine du projet, mais Python place le dossier
# du script (scripts/) en tête de sys.path : on ajoute la racine pour pouvoir
# importer le package agent/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.conseil import conseiller

DB_FILE = Path(__file__).resolve().parent.parent / "Frontend" / "db.json"


# Imprime un objet JSON {error, code?} sur stdout pour signaler un échec au process appelant.
def fail(message, code=None):
    payload = {"error": message}
    if code:
        payload["code"] = code
    print(json.dumps(payload, ensure_ascii=False))


def _parse_recent(value):
    """Parse le champ optionnel 'recent' : liste JSON de noms, ou chaîne 'Nom 1|Nom 2'."""
    if value is None:
        return None
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str):
        items = [s.strip() for s in value.split("|") if s.strip()]
        return items or None
    return None


# Lit la requête JSON sur stdin, charge la garde-robe de l'utilisateur et génère une tenue via conseiller().
def main():
    try:
        payload = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        return fail("Entrée JSON invalide (attendu : {userId, demande}).")

    user_id = payload.get("userId")
    demande = payload.get("demande")
    if not user_id or not demande:
        return fail("userId et demande sont requis.")

    with open(DB_FILE, "r", encoding="utf-8") as f:
        db = json.load(f)

    wardrobe = db.get("wardrobe", {}).get(user_id)
    if wardrobe is None:
        return fail("Garde-robe introuvable pour cet utilisateur.", code="WARDROBE_NOT_FOUND")

    profil = next((p for p in db.get("profiles", []) if p.get("userId") == user_id), {})
    recent_items = _parse_recent(payload.get("recent"))

    try:
        if recent_items is not None:
            result = conseiller(wardrobe=wardrobe, profil=profil, demande=demande, recent_items=recent_items)
        else:
            result = conseiller(wardrobe=wardrobe, profil=profil, demande=demande)
    except Exception as e:
        return fail(str(e))

    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
