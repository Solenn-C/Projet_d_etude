# ============================================================
# Backend/services/outfit_model.py
# ============================================================
# RÔLE : Modèle de recommandation de tenues par scoring vectoriel
#        (cosine similarity) sur la garde-robe de l'utilisateur.
#
# DESCRIPTION :
#   1. Chaque vêtement est encodé en vecteur de features (saisons,
#      famille de couleur) via MultiLabelBinarizer.
#   2. Pour chaque tenue, on génère des combinaisons candidates
#      (haut+bas ou ensemble) + chaussures + accessoire/manteau,
#      on les score par cohérence (cosine similarity) avec une
#      pénalité si les couleurs ne sont pas compatibles, et on
#      garde la meilleure combinaison non encore utilisée.
#   3. recommander_tenues() répète ce tirage `nb` fois pour
#      proposer plusieurs tenues différentes.
#
# FONCTIONS / ENDPOINTS PRINCIPAUX :
#   - _famille_couleur(couleur)              : classe une couleur (neutre/chaude/froide/pastel/autre)
#   - _couleurs_compatibles(c1, c2)          : vrai si deux couleurs sont compatibles
#   - _vectoriser(item)                       : encode un vêtement en vecteur numérique
#   - _score_coherence(items)                 : score de cohérence (0-1) d'un ensemble d'articles
#   - _choisir_conseil(styles, contextes)     : sélectionne un conseil texte adapté au style
#   - _style_dominant(styles, contextes)      : détermine le style dominant de la tenue
#   - _contexte_principal(contextes)          : détermine le contexte principal de la tenue
#   - _construire_tenue(...)                  : construit une tenue optimisée (4 articles)
#   - recommander_tenues(...)                 : génère `nb` tenues différentes optimisées
#
# DÉPENDANCES :
#   - sklearn (MultiLabelBinarizer, cosine_similarity), numpy
#   - schemas (GarderobeSchema, VetementSchema, Tenue, PieceTenue)
#
# APPELS ENTRANTS :
#   - Backend/main.py (route /recommander/tenues — endpoint non utilisé par le frontend, voir audit)
#
# APPELS SORTANTS :
#   - (aucun)
# ============================================================

import json
import random
import os
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from sklearn.preprocessing import MultiLabelBinarizer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np

from schemas import GarderobeSchema, VetementSchema, Tenue, PieceTenue

BASE_DIR = Path(__file__).parent.parent.parent

# ── Palettes de compatibilité couleur ────────────────────────────────
COULEURS_NEUTRES = {"blanc", "noir", "gris", "beige", "crème", "ivoire", "marine", "bleu marine"}
COULEURS_CHAUDES  = {"rouge", "orange", "jaune", "bordeaux", "terracotta", "corail"}
COULEURS_FROIDES  = {"bleu", "vert", "violet", "bleu ciel", "turquoise", "menthe"}
COULEURS_PASTEL   = {"rose pastel", "bleu pastel", "lavande", "pêche", "vert d'eau"}

# Classe une couleur dans une famille (neutre/chaude/froide/pastel/autre) selon des listes de mots-clés.
def _famille_couleur(couleur: str) -> str:
    if not couleur:
        return "neutre"
    c = couleur.lower()
    for n in COULEURS_NEUTRES:
        if n in c: return "neutre"
    for n in COULEURS_CHAUDES:
        if n in c: return "chaude"
    for n in COULEURS_FROIDES:
        if n in c: return "froide"
    for n in COULEURS_PASTEL:
        if n in c: return "pastel"
    return "autre"

def _couleurs_compatibles(c1: str, c2: str) -> bool:
    """Deux couleurs sont compatibles si même famille ou si l'une est neutre."""
    f1, f2 = _famille_couleur(c1), _famille_couleur(c2)
    if f1 == "neutre" or f2 == "neutre":
        return True
    return f1 == f2

# ── Compatibilité style / contexte ───────────────────────────────────
STYLE_CONTEXTE: Dict[str, List[str]] = {
    "Bohème":      ["quotidien", "voyage", "festival"],
    "Romantique":  ["quotidien", "soiree", "bureau"],
    "Vintage":     ["quotidien", "soiree"],
    "Casual":      ["quotidien", "sport", "voyage"],
    "Minimaliste": ["bureau", "quotidien", "soiree"],
    "Sportswear":  ["sport", "quotidien"],
    "Élégant":     ["bureau", "soiree"],
}

CONSEILS_PAR_STYLE: Dict[str, List[str]] = {
    "Bohème":      [
        "Misez sur les superpositions légères pour un look bohème authentique.",
        "Les matières fluides et naturelles sont la clé du style bohème.",
        "Ajoutez une touche de broderie ou de dentelle pour compléter la tenue.",
    ],
    "Romantique":  [
        "Les volumes doux et les imprimés fleuris magnifient ce look romantique.",
        "Une touche de dentelle ou de soie sublime cette tenue.",
        "Les couleurs pastel renforcent l'élégance romantique de cet ensemble.",
    ],
    "Vintage":     [
        "L'équilibre entre pièces modernes et vintage crée un look unique.",
        "Les accessoires rétro sont la touche finale parfaite.",
        "Misez sur les coupes d'époque pour un style vintage assumé.",
    ],
    "Casual":      [
        "Le confort avant tout — cette tenue est parfaite pour une journée active.",
        "Simple mais efficace, ce combo fonctionne dans toutes les situations.",
        "Ajoutez une veste pour habiller ce look casual en un instant.",
    ],
    "Minimaliste": [
        "Moins c'est plus — cette tenue épurée parle d'elle-même.",
        "La qualité des matières fait la différence dans un look minimaliste.",
        "Les lignes nettes et les couleurs unies créent une élégance discrète.",
    ],
    "Élégant":     [
        "La coupe fait tout dans ce look élégant et structuré.",
        "Les accessoires discrets achèvent parfaitement cette tenue chic.",
        "Misez sur des matières nobles pour un résultat impeccable.",
    ],
}

# ── Encodage vectoriel ────────────────────────────────────────────────
ALL_CATEGORIES = ["haut", "bas", "manteau", "ensemble", "chaussures", "accessoires"]
ALL_STYLES     = list(STYLE_CONTEXTE.keys())
ALL_SAISONS    = ["Printemps", "Été", "Automne", "Hiver"]
ALL_FAMILLES   = ["neutre", "chaude", "froide", "pastel", "autre"]

mlb_styles  = MultiLabelBinarizer(classes=ALL_STYLES)
mlb_saisons = MultiLabelBinarizer(classes=ALL_SAISONS)
mlb_familles= MultiLabelBinarizer(classes=ALL_FAMILLES)

mlb_styles.fit([[]])
mlb_saisons.fit([[]])
mlb_familles.fit([[]])

def _vectoriser(item: VetementSchema) -> np.ndarray:
    """Encode un vêtement en vecteur numérique."""
    saisons_item  = item.saisons or []
    famille_col   = _famille_couleur(item.couleur or "")
    vec_saisons   = mlb_saisons.transform([saisons_item])[0]
    vec_famille   = mlb_familles.transform([[famille_col]])[0]
    vec = np.concatenate([vec_saisons, vec_famille])
    return vec.astype(float)

def _score_coherence(items: List[VetementSchema]) -> float:
    """Score de cohérence d'un ensemble d'articles (0-1)."""
    if len(items) < 2:
        return 1.0
    vecs = [_vectoriser(i) for i in items]
    scores = []
    for i in range(len(vecs)):
        for j in range(i + 1, len(vecs)):
            sim = cosine_similarity([vecs[i]], [vecs[j]])[0][0]
            scores.append(sim)
    return float(np.mean(scores)) if scores else 1.0

def _choisir_conseil(styles: List[str], contextes: List[str]) -> str:
    """Sélectionne un conseil adapté au style dominant."""
    for style in styles:
        conseils = CONSEILS_PAR_STYLE.get(style, [])
        if conseils:
            return random.choice(conseils)
    if "bureau" in contextes:
        return "Tenue professionnelle et soignée pour une journée productive."
    if "soiree" in contextes:
        return "Une tenue qui allie style et élégance pour briller ce soir."
    return "Un look cohérent et bien assemblé pour votre journée."

# Détermine le style dominant à afficher pour la tenue (premier style préféré, sinon déduit du contexte).
def _style_dominant(styles: List[str], contextes: List[str]) -> str:
    if styles:
        return styles[0]
    if "bureau" in contextes:
        return "Professionnel"
    if "soiree" in contextes:
        return "Élégant"
    return "Casual"

# Détermine le contexte principal de la tenue selon un ordre de priorité (soirée > bureau > voyage > sport > quotidien).
def _contexte_principal(contextes: List[str]) -> str:
    priority = ["soiree", "bureau", "voyage", "sport", "quotidien"]
    for c in priority:
        if c in contextes:
            return c
    return contextes[0] if contextes else "quotidien"

# ── Construction des tenues ───────────────────────────────────────────
def _construire_tenue(
    garderobe: GarderobeSchema,
    styles: List[str],
    contextes: List[str],
    deja_utilisees: set = None,
) -> Optional[Tenue]:
    """
    Construit UNE tenue optimisée (4 articles).
    Évite de répéter exactement la même combinaison si deja_utilisees est fourni.
    """
    if deja_utilisees is None:
        deja_utilisees = set()

    hauts      = garderobe.haut      or []
    bas        = garderobe.bas       or []
    ensembles  = garderobe.ensemble  or []
    chaussures = garderobe.chaussures or []
    manteaux   = garderobe.manteau   or []
    accessoires= garderobe.accessoires or []

    has_haut_bas  = len(hauts) >= 1 and len(bas) >= 1
    has_ensemble  = len(ensembles) >= 1

    if not has_haut_bas and not has_ensemble:
        return None
    if not chaussures:
        return None

    meilleur_score = -1.0
    meilleure_combo: Optional[List[VetementSchema]] = None

    # Générer des candidats de base (haut+bas ou ensemble)
    bases_candidates = []
    if has_haut_bas:
        # Mélanger pour varier les propositions
        hauts_shuffled = hauts.copy()
        bas_shuffled   = bas.copy()
        random.shuffle(hauts_shuffled)
        random.shuffle(bas_shuffled)
        for h in hauts_shuffled[:5]:
            for b in bas_shuffled[:5]:
                bases_candidates.append([h, b])
    if has_ensemble:
        ens_shuffled = ensembles.copy()
        random.shuffle(ens_shuffled)
        for e in ens_shuffled[:5]:
            bases_candidates.append([e])

    random.shuffle(bases_candidates)

    # Mélanger les listes annexes une seule fois
    chaussures_s  = random.sample(chaussures,   min(len(chaussures),  5))
    accessoires_s = random.sample(accessoires,  min(len(accessoires), 3))
    manteaux_s    = random.sample(manteaux,     min(len(manteaux),    3))

    def _evaluer(combo: List[VetementSchema]) -> float:
        """Score de cohérence avec pénalité couleur."""
        ids = frozenset(str(i.id) for i in combo)
        if ids in deja_utilisees:
            return -1.0
        couleurs_ok = all(
            _couleurs_compatibles(combo[i].couleur or "", combo[j].couleur or "")
            for i in range(len(combo)) for j in range(i+1, len(combo))
        )
        score = _score_coherence(combo)
        return score * (1.0 if couleurs_ok else 0.7)

    for base in bases_candidates:
        is_ensemble_base = len(base) == 1  # True si base = [ensemble]

        for chaussure in chaussures_s:
            # ── Règle 4 articles ────────────────────────────────────────
            # Haut + Bas  → + Chaussures + (Accessoire OU Manteau)
            # Ensemble    → + Chaussures + Accessoire + Manteau
            if is_ensemble_base:
                # On a besoin des deux : accessoire ET manteau
                candidats_4e = []
                for a in accessoires_s:
                    for m in manteaux_s:
                        candidats_4e.append([a, m])
                # Si manque l'un des deux, on fait avec ce qu'on a
                if not candidats_4e:
                    if accessoires_s:
                        candidats_4e = [[a] for a in accessoires_s]
                    elif manteaux_s:
                        candidats_4e = [[m] for m in manteaux_s]
                    else:
                        candidats_4e = [[]]

                for extras in candidats_4e[:4]:
                    combo = base + [chaussure] + extras
                    score = _evaluer(combo)
                    if score > meilleur_score:
                        meilleur_score = score
                        meilleure_combo = combo
            else:
                # Haut + Bas → 4e pièce = accessoire OU manteau
                quatriemes: List[Optional[VetementSchema]] = accessoires_s + manteaux_s
                if not quatriemes:
                    quatriemes = [None]

                for quatrieme in quatriemes[:4]:
                    combo = base + [chaussure] + ([quatrieme] if quatrieme else [])
                    score = _evaluer(combo)
                    if score > meilleur_score:
                        meilleur_score = score
                        meilleure_combo = combo

    if not meilleure_combo:
        return None

    # Marquer comme utilisée
    deja_utilisees.add(frozenset(str(i.id) for i in meilleure_combo))

    # Construire la réponse — la catégorie vient TOUJOURS de item.categorie
    # (défini par annoter() depuis la liste wardrobe d'origine, pas depuis Groq)
    cat_map = {
        "haut":        "Haut",
        "bas":         "Bas",
        "manteau":     "Manteau",
        "ensemble":    "Ensemble",
        "chaussures":  "Chaussures",
        "accessoires": "Accessoire",
    }
    pieces = []
    for item in meilleure_combo:
        cat_label = cat_map.get(item.categorie or "", "Haut")
        pieces.append(PieceTenue(
            nom=item.nom,
            categorie=cat_label,
            couleur=item.couleur,
        ))

    return Tenue(
        pieces=pieces,
        conseil=_choisir_conseil(styles, contextes),
        style_dominant=_style_dominant(styles, contextes),
        contexte=_contexte_principal(contextes),
    )

def recommander_tenues(
    garderobe: GarderobeSchema,
    styles: List[str],
    contextes: List[str],
    nb: int = 1,
) -> List[Tenue]:
    """
    Génère `nb` tenues différentes optimisées.
    """
    # Annote chaque item de la garde-robe avec sa catégorie d'origine, utilisée pour le scoring et le libellé de la pièce.
    def annoter(items, cat):
        for item in items:
            item.categorie = cat
        return items

    annoter(garderobe.haut,       "haut")
    annoter(garderobe.bas,        "bas")
    annoter(garderobe.manteau,    "manteau")
    annoter(garderobe.ensemble,   "ensemble")
    annoter(garderobe.chaussures, "chaussures")
    annoter(garderobe.accessoires,"accessoires")

    deja_utilisees: set = set()
    tenues: List[Tenue] = []

    tentatives = 0
    max_tentatives = nb * 10

    while len(tenues) < nb and tentatives < max_tentatives:
        tenue = _construire_tenue(garderobe, styles, contextes, deja_utilisees)
        if tenue:
            tenues.append(tenue)
        tentatives += 1

    return tenues
