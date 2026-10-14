# Sprint 0 — Audit de l'API et du code existant

**But :** savoir précisément comment se comporte l'API et ce que fait le code actuel, AVANT d'écrire le moteur.
Aucune fonctionnalité n'est livrée ; on produit des faits vérifiés.
Spec : §5.1, §6.2, §8 (réutilisation), §10 (points à confirmer).

## Tâches
1. **Lire le code existant** et documenter dans `docs/bulk_v2/audit_code.md` :
   - `api_client.py` : méthodes, gestion des erreurs, timeouts (présents ou non), où est lu le token.
   - `module3_bulk_export.py` : boucle de pagination, limite des 1 000 itérations, déduplication via `all_docs`,
     conditions d'arrêt.
   - `build_filter_params()` : paramètres produits ; sont-ils identiques pour `/reviews` et `/metrics` ?
   - `postprocess_reviews()` : lister **chaque** transformation (renommage, suppression, enrichissement, format de date…).
     Classer : « acceptable pour le format analytique » / « interdit pour le JSONL brut ».
   - `display_download_buttons()` : comment les fichiers sont construits (DataFrame en mémoire ?).
2. **Script d'audit API** `scripts/audit_api.py` (lecture seule, petit volume, token pris dans les secrets/env) :
   - Appeler `/metrics` puis paginer `/reviews` avec les mêmes filtres sur un petit périmètre (< 5 000 mentions).
   - Mesurer : taille de page max acceptée pour `rows`, nom et format du champ identifiant,
     comportement en fin de pagination (le curseur renvoyé est-il identique au curseur envoyé ? page vide ?),
     ordre des résultats (stable entre deux parcours ?), taille moyenne d'une mention en octets,
     en-têtes de quota / `Retry-After` exposés, consommation de quota par appel.
   - Comparer le nombre d'IDs uniques récupérés avec le chiffre de `/metrics`.
   - Ne jamais afficher le token. Sauvegarder les résultats bruts de l'audit hors du dépôt (pas de commit de mentions réelles).
3. **Rédiger** `docs/bulk_v2/audit_api.md` avec, pour chaque point : constaté / confirmé par le fournisseur / inconnu.
4. **Préparer** `docs/bulk_v2/questions_fournisseur.md` : les 5 questions de la spec §10, reformulées avec ce que l'audit a déjà montré.

## Ce que vous (humain) devez faire
- Envoyer `questions_fournisseur.md` au fournisseur et reporter les réponses dans `audit_api.md`.

## Ne pas faire
- Aucune modification de code applicatif.
- Ne pas extrapoler : un comportement observé une fois sur petit volume reste marqué « observé, non garanti ».

## Définition de terminé
- [ ] `audit_code.md` et `audit_api.md` existent et sont lisibles par un non-développeur.
- [ ] Le champ ID natif est identifié (nom exact, présent sur 100 % des mentions de l'échantillon ?).
- [ ] La règle de fin de pagination observée est décrite.
- [ ] La liste des transformations de `postprocess_reviews()` est complète.
- [ ] Aucun token ni mention réelle commité.
