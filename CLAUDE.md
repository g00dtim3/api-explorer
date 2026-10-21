# Contexte projet — Bulk Export V2 (api-explorer)

> Ce fichier est lu automatiquement par Claude Code à chaque session.
> S'il existe déjà un `CLAUDE.md` à la racine du dépôt, ajouter ce contenu à la fin.

## Ce qu'on construit
Une nouvelle page Streamlit **Bulk Export V2** dans `g00dtim3/api-explorer`, capable d'exporter
jusqu'à **500 000 mentions** depuis l'API Ratings & Reviews, de façon **traçable, reprenable et vérifiable**.
La spécification complète est dans `docs/bulk_v2/SPEC.md` (spécification fonctionnelle et technique v1.0 du 14/10/2026).

## Règles non négociables (à respecter dans TOUS les sprints)
1. **Ne jamais modifier** `module3_bulk_export.py` ni casser les modules existants. Toute modification
   de `api_client.py` ou `main_app.py` doit rester rétrocompatible.
2. **Jamais de DataFrame global** de 500k lignes. Les données sont écrites au fil de l'eau, page par page.
3. **Données source intactes** : aucun verbatim ni champ source modifié, renommé, tronqué ou "nettoyé"
   dans les fichiers JSONL (référence brute). Les transformations sont réservées au format analytique dérivé.
4. **Un curseur n'est jamais marqué validé avant que les données de sa page soient écrites durablement**
   (fichier écrit + `fsync`, puis transaction SQLite).
5. **COMPLETED uniquement après validation**. Une boucle de pagination qui s'arrête ne suffit pas.
6. **Pas d'identifiant inventé** (compteur, UUID, numéro de ligne). Le champ `id` de l'API n'est pas fiable (régénéré
   à chaque export) : il est conservé tel quel mais n'est **jamais** utilisé comme clé. L'unicité repose sur des empreintes
   SHA-256 calculées uniquement à partir des champs source (`raw_hash`, `content_key`, `compass_id` ; cf.
   `docs/bulk_v2/decision_identifiant.md`). Une mention sans date = erreur explicite. *(Règle révisée le 15/10/2026.)*
7. **Doublon avec contenu différent** = conflit tracé et signalé, jamais fusionné silencieusement.
8. **Secrets** : aucun token dans les logs, `config.json`, manifestes ou messages d'erreur. Masquer systématiquement.
9. **Pas de données inventées** pour prouver un résultat. Les tests unitaires peuvent utiliser de petites
   fixtures synthétiques clairement nommées `fake_*` ; les tests de volumétrie utilisent des exports réels autorisés.
10. **Ne pas deviner le comportement de l'API** : si une hypothèse n'est pas confirmée dans
    `docs/bulk_v2/audit_api.md`, la rendre configurable et la signaler, ne pas la coder en dur.
11. `random` désactivé pour les exports exhaustifs.

## Architecture cible
```
api-explorer/
├── main_app.py                   # + entrée de menu "Bulk Export V2"
├── api_client.py                 # réutilisé, + timeouts / erreurs structurées
├── module3_bulk_export.py        # INCHANGÉ
├── module4_bulk_export_v2.py     # interface Streamlit (4 onglets)
├── bulk_export/
│   ├── __init__.py
│   ├── models.py                 # statuts, dataclasses, config figée
│   ├── state_store.py            # SQLite : état, checkpoints, index des IDs
│   ├── api_adapter.py            # contrat de pagination
│   ├── batches.py                # écriture incrémentale des lots JSONL
│   ├── engine.py                 # orchestration page par page
│   ├── worker.py                 # processus indépendant du navigateur
│   ├── validation.py             # contrôles qualité
│   └── downloads.py              # CSV / ZIP / manifeste
├── docs/bulk_v2/                 # spec, audit, sprints
└── tests/
```

Stockage par export (racine configurable via la variable d'environnement `BULK_EXPORT_DIR`) :
```
exports/{export_id}/config.json, manifest.json, checkpoints.sqlite, export.log,
                    batches/batch_0001.jsonl ..., output/export_complete.csv, export_batches.zip
```

## Statuts
PENDING → RUNNING → (STOPPING → PAUSED) | FAILED | INCOMPLETE → VALIDATING → COMPLETED

## Façon de travailler
- Un sprint à la fois. Lire le fichier du sprint dans `docs/bulk_v2/sprints/` avant de coder.
- Commencer par proposer un plan, attendre validation, puis coder.
- Tests avec `pytest` ; chaque sprint se termine avec tous les tests au vert (anciens compris).
- À la fin du sprint : mettre à jour `docs/bulk_v2/JOURNAL.md` (ce qui est fait, décisions, points ouverts),
  puis un commit par sprint sur une branche `feature/bulk-export-v2`.
- Expliquer les choix en français simple : l'utilisateur lit le Python mais n'est pas développeur.

## Mises à jour du 21/10/2026 (chantier « gardening »)
- **Branche** : `feature/bulk-export-v2` est fusionnée dans `main`. Streamlit Cloud déploie `main`.
  Chaque nouveau sprint part d'une nouvelle branche créée depuis `main`, puis une pull request.
- **Architecture réelle** : Postgres Supabase (schéma `bulk_export`) + Supabase Storage, et non plus SQLite
  local ni `BULK_EXPORT_DIR`. `docs/bulk_v2/ADAPTATION_SUPABASE.md` fait foi pour tout ce qui concerne le stockage.
- **Conservation** (lot 1, `docs/chantier/SPRINT_L1A_conservation_du_brut.md`) : le brut reste en base après
  COMPLETED (purge désactivée par défaut) et `retention_days = 0` signifie « ne jamais supprimer les fichiers ».
- **Base partagée** : le même projet Supabase héberge Compass (schéma `public`) et, après le lot 2, Reddit
  (schéma `reddit`). Ne jamais créer, modifier ou supprimer d'objet hors du schéma `bulk_export`.
- **Lien Compass** : `compass_id` doit rester identique, au caractère près, à l'`id` calculé par
  `compass_import/core/hasher.py` (dépôt `mvp_verbatim_import`). Toute modification de l'une des deux
  méthodes se fait des deux côtés, avec le test commun (fixture `fake_export_plat`).
