# Sprint 7 — Recette réelle 500 000 mentions et optimisation

**But :** prouver, sur données réelles autorisées et sur Streamlit Cloud, que les 12 critères d'acceptation
de la spec (§9) sont tenus, puis améliorer ce qui coince.
Spec : §9, §10 (phase 6). Adaptation : §4, §6.
Dépend de : sprint 6.

## Décision humaine préalable
Choisir un périmètre réel d'environ 500 000 mentions **autorisé** (filtres exacts, quota disponible) et le noter dans `JOURNAL.md`.

## Tâches
1. Mesures pendant un export (affichées dans le Monitor ou écrites dans `events`) : mémoire du processus Streamlit,
   durée, pages/minute, temps moyen d'un `commit_page`, appels API, tentatives, quota consommé,
   espace utilisé dans Postgres et Storage.
2. Recette dans cet ordre, résultats consignés dans `docs/bulk_v2/RECETTE.md` :
   1. Petit export réel (~5 000) de bout en bout → COMPLETED.
   2. Export ~50 000 avec arrêt manuel puis reprise.
   3. Export ~50 000 avec **redémarrage de l'application** au milieu, puis reprise.
   4. Export ~500 000 complet, avec un rechargement du navigateur en cours de route
      (et reprises si l'application redémarre d'elle-même — les compter).
   5. Si le quota le permet : comparer les IDs d'un export interrompu et d'un export d'une traite sur le même périmètre.
3. Cocher la checklist §9 dans `RECETTE.md`, avec la preuve de chaque point (chiffre, capture, extrait du manifeste).
   Le critère « rechargement du navigateur » est tenu ; noter honnêtement le comportement en cas de redémarrage de l'app.
4. Optimisations seulement si une mesure le justifie : taille `rows` (dans les limites confirmées), insertion groupée
   (`COPY` ou `executemany`), index, fréquence de rafraîchissement du Monitor, taille des paquets de lecture.
   Chaque optimisation : mesure avant / après dans `JOURNAL.md`.
5. Si les redémarrages de l'application rendent l'export de 500k pénible → recommander le sprint 8.
6. Rédiger un guide utilisateur court `docs/bulk_v2/GUIDE.md`.

## Règles
- Aucune donnée fabriquée pour la volumétrie. Un critère non démontré reste non coché, avec l'explication.
- Ne pas commiter de mentions réelles ni de fichiers d'export.

## Définition de terminé
- [ ] Les 12 critères de la spec §9 sont cochés avec preuve, ou explicitement signalés non tenus.
- [ ] Tous les tests passent.
- [ ] Pull request de `feature/bulk-export-v2` prête à relire.
