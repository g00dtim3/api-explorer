# Sprint 6 — Validation, manifeste, téléchargements et historique

**But :** ne déclarer un export COMPLETED que s'il est prouvé complet, et fournir des fichiers auditables.
Spec : §4.4, §4.5, §6.2, §6.3, §7.
Dépend de : sprint 5.

## En une phrase
Après la collecte, on vérifie tout ; si une preuve manque, l'export reste INCOMPLETE ou FAILED, avec la raison.

## Tâches
1. `bulk_export/validation.py` — lancé automatiquement par le worker après la collecte (statut VALIDATING) :
   | Contrôle | Règle | Échec |
   |---|---|---|
   | Complétude | uniques == attendu `/metrics` (égalité stricte) | INCOMPLETE |
   | Pagination | fin confirmée par l'adaptateur | INCOMPLETE ou FAILED |
   | Unicité | relecture des lots : aucun ID en double | FAILED |
   | Intégrité | chaque lot lisible, SHA-256 identique à celui enregistré | FAILED |
   | Conservation | chaque ligne JSON valide, hash de contenu identique à `seen_ids` | FAILED |
   | Cohérence | somme des lignes des lots == total du manifeste == `unique_count` | FAILED |
   | Conflits | conflits > 0 → signalés dans le résultat (statut décidé : INCOMPLETE par défaut, configurable) | — |
   - Relecture en flux (ligne à ligne), jamais tout en mémoire.
   - Option : relancer `/metrics` en fin d'export ; si le chiffre a bougé, le noter
     (« jeu de données modifié pendant l'export, complétude non démontrable »).
   - Résultats détaillés stockés et affichés.
2. `bulk_export/downloads.py`
   - `manifest.json` : config (sans secret), `config_hash`, attendu / obtenu, lots (nom, lignes, SHA-256),
     doublons, conflits, erreurs, horodatages, résultats de validation, statut final.
   - `export_complete.csv` construit **en flux** depuis les JSONL : UTF-8 (avec BOM optionnel pour Excel),
     en-têtes = union des champs de premier niveau (pré-calculée en une passe), champs imbriqués en JSON texte,
     textes **inchangés** (le module `csv` gère guillemets et retours ligne).
   - `export_batches.zip` : lots JSONL + manifeste (+ CSV si demandé), écrit en flux.
   - Fichiers générés une seule fois puis servis tels quels (`st.download_button` sur fichier,
     ou lien de téléchargement si la taille dépasse ce que Streamlit supporte bien).
   - Format analytique (CSV plat via `postprocess_reviews()` audité) : **P1**, séparé, nommé clairement « analytique ».
3. **Onglets Downloads et Export History**
   - Downloads : exports COMPLETED uniquement, sans aucun appel API.
   - History : tous les exports (nom, dates, filtres, statut, volumes, fichiers), accès au journal,
     bouton Reprendre si reprenable, téléchargement partiel **étiqueté « DONNÉES PARTIELLES »**.
   - Rétention : durée configurable (variable d'environnement), bouton de suppression manuelle avec confirmation,
     nettoyage automatique des exports terminés trop anciens (jamais d'un export actif ou reprenable sans confirmation).

## Tests (`tests/test_validation.py`, `tests/test_downloads.py`)
- Export complet cohérent → COMPLETED.
- Un ID manquant par rapport à l'attendu → INCOMPLETE.
- Lot modifié après coup (1 caractère) → FAILED (empreinte).
- ID dupliqué injecté dans un lot → FAILED.
- CSV : verbatims avec virgules, guillemets, retours ligne, emojis → relus identiques.
- ZIP contient manifeste + lots ; empreintes du manifeste vérifiables.
- Recherche de secrets : aucun faux token présent dans les fichiers produits.

## Définition de terminé
- [ ] Tous les tests passent, anciens compris.
- [ ] Impossible d'obtenir COMPLETED sans passer par la validation (test dédié).
