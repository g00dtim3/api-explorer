# Sprint 3 — Moteur d'export : pages, déduplication, commit transactionnel

**But :** le cœur du système. Une boucle qui lit l'API page par page, écarte les doublons et enregistre chaque page
**avec** son point de reprise dans une seule transaction Postgres.
Spec : §5.1, §5.2, §5.3, §5.4. Adaptation : §2 (lignes « Écriture des lots » et « Point de reprise »).
Dépend de : sprints 1 et 2.

## En une phrase
Pour chaque page : on lit → on vérifie → on enregistre « mentions + où reprendre » d'un seul coup dans Supabase.
Soit tout est enregistré, soit rien : impossible de valider un curseur sans ses données.

## Tâches
1. `bulk_export/dedup.py`
   - `raw_json` = `json.dumps(record, ensure_ascii=False, separators=(",", ":"))` du dictionnaire reçu, **sans aucune
     modification** de son contenu.
   - `content_hash` = SHA-256 du JSON canonique (`sort_keys=True`) — sert seulement à comparer.
   - Classement de chaque mention de la page :
     ID inconnu → nouvelle ; ID connu + même hash → doublon compté ;
     ID connu + hash différent → **conflit** (enregistré dans `conflicts`, événement d'alerte, contenu d'origine conservé).
   - Doublons **à l'intérieur d'une même page** gérés aussi.
   - Recherche des IDs déjà vus : une seule requête par page (`WHERE mention_id = ANY(%s)`), jamais toute la liste en mémoire.
2. `bulk_export/engine.py` — `ExportEngine.run(export_id, should_stop)` :
   1. Charger l'état ; repartir de `last_committed_cursor` (ou curseur initial).
   2. Boucle : `fetch_page` → classement dédup → `commit_page` (transaction unique) → curseur suivant.
   3. Après chaque page : renouveler le bail ; si `stop_requested` ou `should_stop()` → PAUSED proprement.
   4. Fin confirmée par l'adaptateur → `pagination_finished = true` → statut **INCOMPLETE** (en attente de la
      validation du sprint 6). Jamais COMPLETED ici.
   5. Erreur persistante → FAILED avec `error_details` (sans secret) ; les pages déjà validées restent intactes.
   6. Perte de connexion à la base pendant le commit → la transaction est annulée ; on réessaie la **même page**
      (même curseur) : grâce à la clé primaire, aucun doublon possible.
   7. Dépassement de la limite d'itérations → FAILED avec message clair.
   - Mémoire : seule la page courante est en mémoire. Aucun DataFrame.
   - Le moteur ne dépend pas de Streamlit (importable et testable seul).

## Tests (`tests/test_engine.py`)
- Unitaires avec `fake_api_client` et un faux `state_store` en mémoire :
  - 3 pages → bons compteurs, bon ordre (`seq`).
  - Doublon identique entre deux pages, et à l'intérieur d'une page → compté, enregistré une fois.
  - Doublon à contenu différent → conflit tracé, contenu d'origine conservé.
  - Fin de boucle → INCOMPLETE, pas COMPLETED.
  - Stop demandé → PAUSED ; reprise → même résultat qu'un export d'une traite.
- Intégration (schéma de test) :
  - Verbatim avec accents, emojis, retours ligne, guillemets → `raw_json` relu et redécodé identique au dictionnaire d'origine.
  - **Plantage simulé** pendant `commit_page` → rien n'est enregistré pour cette page ; reprise → aucune perte, aucun doublon
    (comparer la liste d'IDs avec un export non interrompu).
  - Plantage simulé juste après le commit → reprise à la page suivante.

## Ne pas faire
- Pas d'interface, pas de tâche d'arrière-plan (sprint 4).
- Pas de `postprocess_reviews()` dans ce flux.
- Pas de fichier local pour les données.

## Définition de terminé
- [ ] Tous les tests passent, anciens compris.
- [ ] `JOURNAL.md` explique pourquoi « une page = une transaction » protège contre les pertes et les doublons.
