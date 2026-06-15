# ============================================================
# Backend/services/pieces_manquantes.py
# ============================================================
# RÔLE : Moteur de recommandation des pièces manquantes dans la
#        garde-robe, avec score de complétude (0-100).
#
# DESCRIPTION :
#   Analyse une garde-robe (GarderobeSchema) en 3 niveaux :
#     1. Essentiels absolus (catégories vides → impossible de
#        composer une tenue : haut/ensemble, bas/ensemble, chaussures)
#     2. Couverture de style : pour chaque style préféré, vérifie
#        si des pièces caractéristiques (via mots-clés STYLES_PIECES)
#        sont présentes dans la garde-robe
#     3. Contextes & saison : pièces requises par les usages déclarés
#        (CONTEXTES_REQUIS) et par la saison courante (manteau en hiver/automne)
#   Le score reflète la couverture stylistique, pas juste le nombre
#   de catégories non vides.
#
# FONCTIONS / ENDPOINTS PRINCIPAUX :
#   - _saison_actuelle()                  : déduit la saison courante du mois
#   - _items_de(garderobe, cat)           : renvoie les items d'une catégorie de la garde-robe
#   - _noms_de(garderobe, cat)            : renvoie les noms (en minuscules) des items d'une catégorie
#   - _possede_type(noms, mots_cles)       : vrai si un nom contient un des mots-clés
#   - analyser_pieces_manquantes(...)      : calcule pieces_manquantes + score_completude
#   - _sugg_style(cat, styles)             : suggestions de pièces pour une catégorie selon les styles
#
# DÉPENDANCES :
#   - schemas (GarderobeSchema, PieceManquante)
#
# APPELS ENTRANTS :
#   - Backend/main.py (route /recommander/pieces-manquantes)
#
# APPELS SORTANTS :
#   - (aucun)
# ============================================================

from datetime import date
from typing import List, Dict, Tuple
from schemas import GarderobeSchema, PieceManquante

# ── Pièces caractéristiques par style ET catégorie ───────────────────
# Clés = mots-clés qui doivent apparaître dans le nom des articles existants
# Values = suggestions à afficher si absent

STYLES_PIECES: Dict[str, Dict[str, Tuple[List[str], List[str]]]] = {
    # Format : "style": { "categorie": ([mots_cles_a_chercher], [suggestions]) }
    "Bohème": {
        "haut":        (["blouse", "fluide", "volant", "brodé", "transparent"],
                        ["blouse fluide", "top à volants", "chemisier brodé"]),
        "bas":         (["jupe longue", "maxi", "fluide", "large", "fleur"],
                        ["jupe longue", "pantalon large", "jupe à fleurs"]),
        "chaussures":  (["sandale", "botte", "mule"],
                        ["sandales plates", "bottines", "mules"]),
        "accessoires": (["chapeau", "osier", "collier", "bijou", "foulard"],
                        ["chapeau de paille", "sac en osier", "colliers layering"]),
        "manteau":     (["kimono", "cardigan", "velours"],
                        ["kimono", "long cardigan", "veste en velours"]),
    },
    "Romantique": {
        "haut":        (["blouse", "dentelle", "col", "nouer", "soie"],
                        ["blouse à nouer", "top dentelle", "chemisier col lavallière"]),
        "bas":         (["midi", "plissé", "tailleur", "jupe"],
                        ["jupe midi", "jupe plissée", "pantalon tailleur"]),
        "chaussures":  (["ballerine", "escarpin", "talon", "mule"],
                        ["ballerines", "escarpins", "mules à talon"]),
        "accessoires": (["sac", "foulard", "boucle", "bijou"],
                        ["sac structuré", "foulard", "boucles d'oreilles"]),
        "manteau":     (["long", "trench", "cintré"],
                        ["manteau long", "trench", "veste cintrée"]),
    },
    "Vintage": {
        "haut":        (["carreaux", "col roulé", "graphique", "imprimé", "rétro"],
                        ["chemise à carreaux", "pull col roulé", "t-shirt graphique"]),
        "bas":         (["taille haute", "plissé", "large", "vintage"],
                        ["jean taille haute", "jupe midi plissée", "pantalon large"]),
        "chaussures":  (["mocassin", "derby", "bottine"],
                        ["mocassins", "derbies", "bottines à talon"]),
        "accessoires": (["ceinture", "lunette", "bandoulière", "vintage"],
                        ["ceinture vintage", "lunettes rondes", "sac bandoulière"]),
        "manteau":     (["jean", "blazer", "laine", "oversize"],
                        ["veste en jean", "blazer oversize", "manteau en laine"]),
    },
    "Casual": {
        "haut":        (["t-shirt", "sweat", "côtelé", "basique"],
                        ["t-shirt basique", "sweat-shirt", "top côtelé"]),
        "bas":         (["jean", "slim", "droit", "jogging"],
                        ["jean slim", "jean droit", "jogging chic"]),
        "chaussures":  (["sneaker", "basket", "tennis"],
                        ["sneakers", "baskets", "tennis"]),
        "accessoires": (["cabas", "bonnet", "casquette"],
                        ["sac cabas", "bonnet", "casquette"]),
        "manteau":     (["zippé", "parka", "blouson"],
                        ["veste zippée", "parka", "blouson"]),
    },
    "Minimaliste": {
        "haut":        (["uni", "simple", "basique", "chemise", "pull"],
                        ["top sans coutures", "chemise blanche", "pull fin"]),
        "bas":         (["droit", "brut", "simple"],
                        ["pantalon droit", "jean brut", "jupe droite"]),
        "chaussures":  (["mocassin", "sneaker", "mule", "blanc"],
                        ["mocassins", "sneakers blancs", "mules"]),
        "accessoires": (["structuré", "montre", "ceinture fine"],
                        ["sac structuré", "montre", "ceinture fine"]),
        "manteau":     (["camel", "blazer", "trench", "beige"],
                        ["manteau camel", "blazer structuré", "trench beige"]),
    },
    "Sportswear": {
        "haut":        (["sport", "technique", "brassière", "crop"],
                        ["crop top de sport", "t-shirt technique", "brassière"]),
        "bas":         (["legging", "short", "jogging"],
                        ["legging", "short de sport", "jogging"]),
        "chaussures":  (["running", "sport", "basket"],
                        ["sneakers running", "baskets montantes"]),
        "accessoires": (["sport", "casquette", "montre"],
                        ["sac de sport", "casquette", "montre connectée"]),
        "manteau":     (["coupe-vent", "sport", "hoodie"],
                        ["coupe-vent", "veste de sport", "hoodie"]),
    },
    "Élégant": {
        "haut":        (["soie", "structuré", "col v", "élégant"],
                        ["blouse soie", "top structuré", "chemisier col V"]),
        "bas":         (["tailleur", "crayon", "midi"],
                        ["pantalon tailleur", "jupe crayon", "jupe midi"]),
        "chaussures":  (["escarpin", "talon", "mule"],
                        ["escarpins", "mules à talon", "bottines à talon"]),
        "accessoires": (["pochette", "bijou", "fin", "cuir"],
                        ["sac pochette", "bijoux fins", "ceinture cuir"]),
        "manteau":     (["long", "blazer", "cuir", "ajusté"],
                        ["manteau long", "blazer ajusté", "veste en cuir"]),
    },
}

CONTEXTES_REQUIS: Dict[str, Dict] = {
    "bureau":    {"essentiels": ["haut","bas","chaussures"], "recommandes": ["manteau"]},
    "quotidien": {"essentiels": ["haut","bas","chaussures"], "recommandes": ["accessoires"]},
    "soiree":    {"essentiels": ["haut","bas","chaussures","accessoires"], "recommandes": []},
    "sport":     {"essentiels": ["haut","bas","chaussures"], "recommandes": []},
    "voyage":    {"essentiels": ["haut","bas","chaussures","manteau"], "recommandes": ["accessoires"]},
}

# Déduit la saison courante (Printemps/Été/Automne/Hiver) à partir du mois actuel.
def _saison_actuelle() -> str:
    m = date.today().month
    if m in (3,4,5):   return "Printemps"
    if m in (6,7,8):   return "Été"
    if m in (9,10,11): return "Automne"
    return "Hiver"

# Renvoie la liste des items d'une catégorie de la garde-robe (liste vide si absente).
def _items_de(garderobe: GarderobeSchema, cat: str) -> list:
    return getattr(garderobe, cat, []) or []

# Renvoie les noms (en minuscules) des items d'une catégorie, pour le matching par mots-clés.
def _noms_de(garderobe: GarderobeSchema, cat: str) -> List[str]:
    return [(i.nom or "").lower() for i in _items_de(garderobe, cat)]

def _possede_type(noms: List[str], mots_cles: List[str]) -> bool:
    """Vérifie si au moins un article contient l'un des mots-clés."""
    return any(
        any(mot in nom for mot in mots_cles)
        for nom in noms
    )

# Calcule la liste des pièces manquantes (essentiels, styles, contextes, saison) et un score de complétude 0-100.
def analyser_pieces_manquantes(
    garderobe: GarderobeSchema,
    styles: List[str],
    contextes: List[str],
    genre: str = "Femme",
    saison: str = None,
) -> Tuple[List[PieceManquante], int]:

    saison = saison or _saison_actuelle()
    pieces_manquantes: List[PieceManquante] = []
    deja_ajoutees = set()  # (categorie, style) pour éviter doublons

    # Ajoute une PieceManquante à la liste, sauf si une entrée avec la même clé existe déjà (anti-doublon).
    def ajouter(cat_label: str, raison: str, priorite: str, suggestions: List[str], cle: str = None):
        k = cle or (cat_label + raison[:20])
        if k not in deja_ajoutees:
            deja_ajoutees.add(k)
            pieces_manquantes.append(PieceManquante(
                categorie=cat_label,
                raison=raison,
                priorite=priorite,
                suggestions=suggestions[:4],
            ))

    cat_map = {
        "haut": "Haut", "bas": "Bas", "manteau": "Manteau",
        "ensemble": "Ensemble", "chaussures": "Chaussures", "accessoires": "Accessoires",
    }

    # ── 1. Essentiels absolus ─────────────────────────────────────────
    has_haut = len(_items_de(garderobe, "haut")) > 0
    has_bas  = len(_items_de(garderobe, "bas"))  > 0
    has_ens  = len(_items_de(garderobe, "ensemble")) > 0
    has_chaus= len(_items_de(garderobe, "chaussures")) > 0

    if not has_haut and not has_ens:
        ajouter("Haut", "Aucun haut — impossible de composer une tenue complète.", "haute",
                _sugg_style("haut", styles), "haut_absent")
    if not has_bas and not has_ens:
        ajouter("Bas", "Aucun bas — impossible de composer une tenue complète.", "haute",
                _sugg_style("bas", styles), "bas_absent")
    if not has_chaus:
        ajouter("Chaussures", "Aucune chaussure — une tenue nécessite obligatoirement une paire.", "haute",
                _sugg_style("chaussures", styles), "chaus_absent")

    # ── 2. Couverture de style (le cœur du moteur) ────────────────────
    # Pour chaque style préféré, vérifie si des pièces caractéristiques
    # sont présentes dans la garde-robe. Recommande ce qui manque.

    cats_a_verifier = ["haut", "bas", "chaussures", "accessoires", "manteau"]

    for style in styles:
        regles_style = STYLES_PIECES.get(style)
        if not regles_style:
            continue

        for cat, (mots_cles, suggestions) in regles_style.items():
            if cat not in cats_a_verifier:
                continue
            noms = _noms_de(garderobe, cat)

            # Si la catégorie est vide, déjà géré ci-dessus
            if not noms:
                continue

            # Si aucun article ne correspond aux mots-clés du style
            if not _possede_type(noms, mots_cles):
                nb = len(noms)
                raison = (
                    f"Vous avez {nb} {cat_map.get(cat,'article')}(s) mais aucun ne correspond "
                    f"au style {style}. Ajoutez : {', '.join(suggestions[:2])}."
                )
                ajouter(
                    cat_map.get(cat, cat.capitalize()),
                    raison,
                    "moyenne",
                    suggestions,
                    cle=f"style_{style}_{cat}",
                )

    # ── 3. Contextes déclarés ─────────────────────────────────────────
    for ctx in contextes:
        regles = CONTEXTES_REQUIS.get(ctx.lower())
        if not regles:
            continue
        for cat in regles["essentiels"]:
            if len(_items_de(garderobe, cat)) == 0:
                ajouter(cat_map.get(cat, cat.capitalize()),
                        f"Indispensable pour votre contexte « {ctx} ».",
                        "haute", _sugg_style(cat, styles), f"ctx_{ctx}_{cat}")
        for cat in regles["recommandes"]:
            if len(_items_de(garderobe, cat)) == 0:
                ajouter(cat_map.get(cat, cat.capitalize()),
                        f"Recommandé pour « {ctx} » — complète vos tenues.",
                        "faible", _sugg_style(cat, styles), f"ctx_rec_{ctx}_{cat}")

    # ── 4. Saison ─────────────────────────────────────────────────────
    if saison in ("Hiver", "Automne") and len(_items_de(garderobe, "manteau")) == 0:
        ajouter("Manteau", f"En {saison}, un manteau est indispensable.",
                "moyenne", _sugg_style("manteau", styles), "saison_manteau")

    # ── 5. Score : proportion de cases style couvertes ────────────────
    total_cases = 0
    cases_ok    = 0
    for style in styles:
        regles_style = STYLES_PIECES.get(style, {})
        for cat, (mots_cles, _) in regles_style.items():
            noms = _noms_de(garderobe, cat)
            total_cases += 1
            if noms and _possede_type(noms, mots_cles):
                cases_ok += 1

    # Bonus : catégories essentielles remplies
    essentiels_ok = sum([has_haut or has_ens, has_bas or has_ens, has_chaus])
    if total_cases > 0:
        score = round((cases_ok / total_cases) * 70 + (essentiels_ok / 3) * 30)
    else:
        score = round((essentiels_ok / 3) * 100)

    score = max(0, min(100, score))
    return pieces_manquantes, score


def _sugg_style(cat: str, styles: List[str]) -> List[str]:
    """Suggestions de pièces pour une catégorie selon les styles."""
    suggestions = []
    for style in styles:
        regles = STYLES_PIECES.get(style, {})
        if cat in regles:
            _, sugg = regles[cat]
            for s in sugg:
                if s not in suggestions:
                    suggestions.append(s)
    if not suggestions:
        defaults = {
            "haut":        ["t-shirt basique", "chemise", "pull"],
            "bas":         ["jean droit", "pantalon chino", "jupe midi"],
            "chaussures":  ["sneakers", "mocassins", "bottines"],
            "accessoires": ["sac à main", "ceinture", "écharpe"],
            "manteau":     ["trench", "manteau en laine", "veste en jean"],
            "ensemble":    ["combinaison", "ensemble deux pièces"],
        }
        suggestions = defaults.get(cat, [])
    return suggestions[:4]
