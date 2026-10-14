# Sprint 0 — Audit de l'API, du code existant et de la volumétrie

**But :** savoir précisément comment se comporte l'API et ce que fait le code actuel, AVANT d'écrire le moteur.
Aucune fonctionnalité n'est livrée ; on produit des faits vérifiés.
Spec : §5.1, §6.2, §8 (réutilisation), §10. Adaptation : §6 (volumétrie).

## Tâches
1. **Lire le code existant** et documenter dans `docs/bulk_v2/audit_code.md` :
   - `api_client.py` : méthodes, gestion des erreurs, timeouts (présents ou non), où est lu le token.
   - `module3_bulk_export.py` : boucle de pagination, limite des 1 000 itérations, déduplication via `all_docs`,
     conditions d'arrêt.
   - `build_filter_params()` : paramètres produits ; sont-ils identiques pour `/reviews` et `/metrics` ?
   - `postprocess_reviews()` : lister **chaque** transformation (renommage, suppression, enrichissement, format de date…).
     Classer : « acceptable pour le format analytique » / « interdit pour les données brutes ».
   - `display_download_buttons()` : comment les fichiers sont construits (DataFrame en mémoire ?).
   - `requirements.txt` et version de Streamlit utilisée (utile pour le sprint 5).
2. **Script d'audit API** `scripts/audit_api.py` (lecture seule, petit volume, token lu dans les secrets/env) :
   - Appeler `/metrics` puis paginer `/reviews` avec les mêmes filtres sur un petit périmètre (< 5 000 mentions).
   - Mesurer : taille de page max acceptée pour `rows`, nom et format du champ identifiant,
     comportement en fin de pagination (curseur renvoyé identique au curseur envoyé ? page vide ?),
     ordre des résultats (stable entre deux parcours ?), en-têtes de quota / `Retry-After`,
     consommation de quota par appel, temps moyen de réponse par page.
   - **Volumétrie** : taille moyenne d'une mention en octets (texte JSON brut) et taille compressée gzip
     → extrapoler l'espace nécessaire pour 500 000 mentions (Postgres pendant la collecte + Storage pour les fichiers finaux)
     et la durée probable d'un export complet.
   - Comparer le nombre d'IDs uniques récupérés avec le chiffre de `/metrics`.
   - Ne jamais afficher le token. Ne pas commiter les réponses brutes (mentions réelles).
3. **Rédiger** `docs/bulk_v2/audit_api.md` : pour chaque point, statut « constaté » / « confirmé par le fournisseur » / « inconnu ».
4. **Préparer** `docs/bulk_v2/questions_fournisseur.md` : les 5 questions de la spec §10, reformulées avec ce que
   l'audit a déjà montré. La question « Hébergement » est réglée (voir `ADAPTATION_SUPABASE.md`) : la retirer.

## Ce que vous (humain) devez faire
- Envoyer `questions_fournisseur.md` au fournisseur et reporter les réponses dans `audit_api.md`.

## Ne pas faire
- Aucune modification de code applicatif.
- Ne pas extrapoler : un comportement observé une fois sur petit volume reste « observé, non garanti ».

## Définition de terminé
- [ ] `audit_code.md` et `audit_api.md` existent et sont lisibles par un non-développeur.
- [ ] Le champ ID natif est identifié (nom exact, présent sur 100 % des mentions de l'échantillon ?).
- [ ] La règle de fin de pagination observée est décrite.
- [ ] La liste des transformations de `postprocess_reviews()` est complète.
- [ ] Estimation chiffrée de l'espace et de la durée pour 500 000 mentions.
- [ ] Aucun token ni mention réelle commité.
