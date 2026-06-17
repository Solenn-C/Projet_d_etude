# Backlog Projet — Fashion Assistant IA

---

## EPIC 1 — Scraping & Constitution du catalogue

| ID | Tâche | Responsable | Statut |
|----|-------|-------------|--------|
| S-01 | Scraper H&M — vêtements homme/femme | Coline | ✅ Done |
| S-02 | Scraper Zara — vêtements homme/femme | Coline | ✅ Done |
| S-03 | Scraper ASOS | Coline | ✅ Done |
| S-04 | Scraper Jules | Coline | ✅ Done |
| S-05 | Scraper Le Coq Sportif | Coline | ✅ Done |
| S-06 | Scraper Mango — robes, tops, jupes femme | Coline | ✅ Done |
| S-07 | Pipeline multiprocessing pour lancer plusieurs scrapers en parallèle | Coline | ✅ Done |
| S-08 | Insertion en base PostgreSQL avec déduplication par URL | Coline | ✅ Done |
| S-09 | Script de reclassification des produits mal catégorisés (règles regex) | Coline | ✅ Done |
| S-10 | Téléchargement des images produits pour constitution du dataset | Coline | ✅ Done |

> **Résultat :** 2 196 produits en base · 30+ marques · images organisées en 23 classes

---

## EPIC 2 — Modèle de reconnaissance de type vestimentaire (CNN)

| ID | Tâche | Responsable | Statut |
|----|-------|-------------|--------|
| M-01 | Préparation du dataset avec fusion hiérarchique des petites classes | Coline | ✅ Done |
| M-02 | Entraînement Phase 1 — MobileNetV2, tête seule (features gelées) | Coline | ✅ Done |
| M-03 | Entraînement Phase 2 — fine-tuning des 5 derniers blocs | Coline | ✅ Done |
| M-04 | Export du modèle au format ONNX | Coline | ✅ Done |
| M-05 | Script de test du modèle sur image locale ou URL | Coline | ✅ Done |
| M-06 | Intégration du modèle ONNX dans le backend FastAPI | À définir | 🔄 À faire |

> **Résultat :** 80% de précision · 23 classes (T-shirt, Jean, Robe, Jupe, Pantalon, Baskets…)

---

## EPIC 3 — Classification des styles de mode

| ID | Tâche | Responsable | Statut |
|----|-------|-------------|--------|
| ST-01 | Ajout de la colonne `style_mode` en base PostgreSQL | Coline | ✅ Done |
| ST-02 | Classification des 2 196 produits du catalogue via API IA (12 styles) | Coline | ✅ Done |
| ST-03 | Classification automatique du `style_mode` à l'ajout d'un nouveau produit | À définir | 🔄 À faire |

> **12 styles :** Casual chic · Minimaliste · Classique · Streetwear · Bohème · Romantique · Élégant · Sportswear · Vintage · Smart casual · Preppy · Avant-garde
> **Résultat :** 2 181/2 196 produits classifiés

---

## EPIC 4 — Agent de conseil vestimentaire

| ID | Tâche | Responsable | Statut |
|----|-------|-------------|--------|
| A-01 | Développement de l'agent de composition de tenue depuis la garde-robe | Coline | ✅ Done |
| A-02 | Prise en compte des styles et contextes préférés du profil utilisateur | Coline | ✅ Done |
| A-03 | Retour structuré : tenue complète + conseil personnalisé | Coline | ✅ Done |
| A-04 | Endpoint FastAPI `POST /api/agent/conseil` | À définir | 🔄 À faire |
| A-05 | Affichage de la tenue recommandée avec photos sur le site | À définir | 🔄 À faire |

> **Exemple :** "J'ai une soirée au restaurant ce soir, compose-moi une tenue élégante"

---

## EPIC 5 — Analyse d'image par IA (vision)

| ID | Tâche | Responsable | Statut |
|----|-------|-------------|--------|
| V-01 | Analyse d'un vêtement seul : couleur, saisons, marque supposée | Coline | ✅ Done |
| V-02 | Endpoint `POST /api/analyse-vetement` + pré-remplissage formulaire garde-robe | À définir | 🔄 À faire |
| V-03 | Analyse d'une tenue complète : détection de tous les vêtements et accessoires | Coline | ✅ Done |
| V-04 | Endpoint `POST /api/analyse-tenue` + ajout multi-vêtements en un clic | À définir | 🔄 À faire |

> **Éléments détectés :** type · couleur · saisons · marque · style global · occasion

---

## Récapitulatif

| Epic | Avancement |
|------|-----------|
| Scraping & catalogue | ✅ Terminé |
| Modèle CNN | ✅ Terminé — intégration site restante |
| Classification styles | ✅ Terminé — automatisation restante |
| Agent conseil | ✅ Logique métier terminée — intégration site restante |
| Analyse vision | ✅ Logique métier terminée — intégration site restante |

### Prochaines tâches prioritaires
1. `POST /api/analyse-vetement` → pré-remplissage formulaire ajout vêtement
2. `POST /api/analyse-tenue` → ajout multi-vêtements depuis une photo
3. `POST /api/agent/conseil` → recommandation de tenue depuis la garde-robe
4. Affichage des tenues recommandées sur le site
5. Classification `style_mode` automatique à l'ajout d'un nouveau produit
