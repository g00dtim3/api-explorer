# Sprint 7 — Recette réelle 500 000 mentions et optimisation

**But :** prouver, sur données réelles autorisées, que les 12 critères d'acceptation de la spec (§9) sont tenus,
puis améliorer ce qui coince (mémoire, temps, quotas, ergonomie).
Spec : §9, §10 (phase 6).
Dépend de : sprint 6.

## Décision humaine préalable
Choisir un périmètre réel d'environ 500 000 mentions **autorisé** (filtres exacts, quota disponible) et le noter dans `JOURNAL.md`.

## Tâches
1. `scripts/measure_export.py` : mesure pendant un export — mémoire max du worker et de Streamlit,
   durée, pages/minute, octets écrits, appels API, tentatives, consommation de quota.
2. Exécuter la recette dans cet ordre, en consignant chaque résultat dans `docs/bulk_v2/RECETTE.md` :
   1. Petit export réel (~5 000) de bout en bout → COMPLETED.
   2. Export ~50 000 avec arrêt manuel puis reprise.
   3. Export ~50 000 avec worker tué (`kill -9`) puis relancé.
   4. Export ~500 000 complet, avec un rechargement du navigateur en cours de route.
   5. Comparaison des IDs : export interrompu vs export d'une traite sur le même périmètre (si le quota le permet).
3. Cocher la checklist §9 dans `RECETTE.md`, avec la preuve de chaque point (chiffre, fichier, capture).
4. Optimisations seulement si une mesure le justifie : taille `rows` (dans les limites confirmées),
   regroupement de commits SQLite, index, fréquence de rafraîchissement du Monitor, taille des lots.
   Chaque optimisation : mesure avant / après dans `JOURNAL.md`.
5. Mettre à jour `docs/bulk_v2/WORKER.md` et rédiger un guide utilisateur court `docs/bulk_v2/GUIDE.md`.

## Règles
- Aucune donnée fabriquée pour la volumétrie. Si un critère n'est pas démontré, il reste non coché avec l'explication.
- Ne pas committer de mentions réelles ni de fichiers d'export.

## Définition de terminé
- [ ] Les 12 critères de la spec §9 sont cochés avec preuve, ou explicitement signalés non tenus.
- [ ] Tous les tests passent.
- [ ] Pull request de `feature/bulk-export-v2` prête à relire.
