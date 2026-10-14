# Sprint 6 — Validation, fichiers finaux dans Supabase Storage, historique et rétention

**But :** ne déclarer un export COMPLETED que s'il est prouvé complet, et fournir des fichiers auditables,
téléchargeables sans relancer la collecte.
Spec : §4.4, §4.5, §6.2, §6.3, §7. Adaptation : §2 (lignes « Écriture des lots », « Téléchargements », « Rétention »).
Dépend de : sprint 5.

## En une phrase
Après la collecte, on fabrique les fichiers à partir de la base, on les envoie dans Storage, on vérifie tout ;
si une preuve manque, l'export reste INCOMPLETE ou FAILED, avec la raison.

## Tâches
1. `bulk_export/storage.py` : envoi, lecture en flux, suppression et **lien signé temporaire** (durée configurable)
   sur le bucket privé. Bibliothèque au choix (`supabase`/`storage3` ou API HTTP), à ajouter à `requirements.txt`.
   Envois volumineux par morceaux / reprise si l'outil le permet ; vérification de la taille après envoi.
2. `bulk_export/downloads.py` — génération **en flux** (lecture de `raw_mentions` par paquets ordonnés par `seq`,
   écriture dans un fichier temporaire, envoi, suppression du temporaire) :
   - Lots `batches/batch_0001.jsonl.gz` … : `raw_json` tel quel, une mention par ligne, `batch_size` mentions par lot.
     SHA-256 calculé sur le contenu non compressé et sur le fichier compressé ; enregistrés dans `files`.
   - `export_complete.csv` : UTF-8 (BOM optionnel pour Excel), en-têtes = union des champs de premier niveau
     (calculée en une première passe), champs imbriqués écrits en texte JSON, textes **inchangés**.
   - `export_batches.zip` : lots + `manifest.json` (+ CSV si demandé).
   - `manifest.json` : config (sans secret), `config_hash`, attendu / obtenu, lots (nom, lignes, SHA-256), doublons,
     conflits, erreurs, horodatages, résultats de validation, statut final.
   - Format analytique (CSV plat via `postprocess_reviews()` audité) : **P1**, fichier séparé, nommé « analytique ».
3. `bulk_export/validation.py` — statut VALIDATING, déclenché automatiquement après la collecte :
   | Contrôle | Règle | Échec |
   |---|---|---|
   | Complétude | uniques == attendu `/metrics` (égalité stricte) | INCOMPLETE |
   | Pagination | `pagination_finished` vrai, fin conforme au contrat | INCOMPLETE ou FAILED |
   | Unicité | relecture des lots depuis Storage : aucun ID en double | FAILED |
   | Intégrité | chaque lot relu depuis Storage, SHA-256 identique à `files` | FAILED |
   | Conservation | chaque ligne relue == `raw_json` en base (hash de contenu identique) | FAILED |
   | Cohérence | somme des lignes des lots == manifeste == `unique_count` | FAILED |
   | Conflits | conflits > 0 → signalés (INCOMPLETE par défaut, configurable) | — |
   - Relecture en flux, jamais tout en mémoire.
   - Relancer `/metrics` en fin d'export ; si le chiffre a bougé : « jeu de données modifié pendant l'export,
     complétude non démontrable » (pas de COMPLETED).
   - Validation elle-même reprenable : si l'application redémarre pendant la validation, on la relance.
4. **Rétention** : après COMPLETED, supprimer les lignes `raw_mentions` de l'export (les fichiers Storage font référence).
   Suppression des fichiers Storage au-delà de `retention_days`, bouton de suppression manuelle avec confirmation.
   Jamais de suppression d'un export actif ou reprenable sans confirmation explicite.
5. **Onglets Downloads et Export History**
   - Downloads : exports COMPLETED ; boutons qui ouvrent un **lien signé** (pas de chargement du fichier dans Streamlit).
     Aucun appel à l'API Ratings & Reviews.
   - History : tous les exports (nom, dates, filtres, statut, volumes, fichiers), journal, bouton Reprendre si reprenable,
     génération d'un fichier partiel **étiqueté « DONNÉES PARTIELLES »** à la demande.

## Tests
- Unitaires (faux stockage) : CSV avec virgules, guillemets, retours ligne, emojis → relus identiques ;
  manifeste complet ; aucun faux secret dans les fichiers produits.
- Intégration (schéma + bucket de test) :
  - Export cohérent → COMPLETED.
  - Un ID manquant par rapport à l'attendu → INCOMPLETE.
  - Lot modifié dans Storage après coup (1 caractère) → FAILED (empreinte).
  - ID dupliqué injecté dans un lot → FAILED.
  - Impossible d'obtenir COMPLETED sans passer par la validation.

## Définition de terminé
- [ ] Tous les tests passent, anciens compris.
- [ ] Un fichier de plusieurs centaines de Mo se télécharge via lien signé sans faire grimper la mémoire de Streamlit.
