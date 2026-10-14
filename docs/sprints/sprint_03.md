# Sprint 3 — Moteur d'export : pages, déduplication, lots, checkpoints

**But :** le cœur du système. Une boucle qui lit l'API page par page, écrit sur disque au fil de l'eau,
écarte les doublons et pose un point de reprise sûr après chaque page.
Spec : §5.1, §5.2, §5.3, §5.4.
Dépend de : sprints 1 et 2.

## En une phrase
Pour chaque page : on lit → on vérifie → on écrit sur disque → on force l'écriture physique → **seulement ensuite**
on note « page validée, voici où reprendre ».

## Tâches
1. `bulk_export/batches.py` — `BatchWriter` :
   - Écrit dans `batches/batch_0001.jsonl`, une mention brute par ligne :
     `json.dumps(record, ensure_ascii=False)` — **aucune transformation** du contenu.
   - Écriture en mode ajout, `flush()` + `os.fsync()` à la fin de chaque page.
   - Bascule sur le lot suivant quand `batch_size` est atteint ; un lot peut contenir une page coupée en deux
     (la correspondance page ↔ lot(s) est enregistrée).
   - Fermeture d'un lot : calcul du SHA-256, nb de lignes, statut CLOSED dans SQLite.
   - `truncate_to(batch_index, line_count)` : au redémarrage, supprime les lignes écrites après le dernier commit
     (lignes « orphelines » d'une page non validée).
2. `bulk_export/dedup.py` :
   - `content_hash` = SHA-256 du JSON canonique (clés triées) de la mention brute.
   - ID inconnu → nouvelle mention ; ID connu + même hash → doublon compté ;
     ID connu + hash différent → **conflit** enregistré dans `conflicts` + événement d'alerte, mention non réécrite.
   - Doublons **à l'intérieur d'une même page** aussi gérés.
   - Recherche des IDs dans SQLite (`seen_ids`), pas dans une liste Python reconstruite à chaque page.
3. `bulk_export/engine.py` — `ExportEngine.run(export_id)` :
   1. Charger l'état ; repartir de `last_committed_cursor` (ou curseur initial).
   2. Réconcilier : tronquer les lignes orphelines du lot courant.
   3. Boucle : `fetch_page` → dédup → écriture + fsync → `commit_page` (transaction SQLite) → curseur suivant.
   4. Après chaque page : vérifier `stop_requested` → si oui, fermer proprement et passer en PAUSED.
   5. Fin confirmée par l'adaptateur → fermer le dernier lot → statut **INCOMPLETE** (en attente de validation,
      sprint 6). Jamais COMPLETED ici.
   6. Erreur persistante → FAILED avec `error_details` (sans secret) ; les données déjà validées restent intactes.
   7. Dépassement de la limite d'itérations → FAILED avec message clair.
   - Mémoire : seule la page courante est en mémoire. Aucun DataFrame.

## Tests (`tests/test_engine.py`) — avec `fake_api_client` et petites fixtures `fake_*`
- 3 pages, batch_size 2 → bons fichiers, bons compteurs, bons hash.
- Doublon identique entre deux pages → compté, écrit une seule fois.
- Doublon à contenu différent → conflit tracé, mention d'origine conservée.
- Verbatim avec accents, emojis, retours ligne, guillemets → relu à l'identique depuis le JSONL.
- **Crash simulé** entre écriture fichier et commit SQLite → au redémarrage, lignes orphelines retirées,
  reprise sans perte ni doublon (comparer à un export non interrompu).
- Crash simulé après commit → reprise à la page suivante.
- Stop demandé → PAUSED, puis reprise → résultat identique à un export d'une traite.
- Fin de boucle → statut INCOMPLETE, pas COMPLETED.

## Ne pas faire
- Pas d'interface, pas de worker (le moteur est appelable directement en Python).
- Pas de `postprocess_reviews()` dans ce flux.

## Définition de terminé
- [ ] Tous les tests passent, anciens compris.
- [ ] `JOURNAL.md` explique l'ordre « écrire → fsync → commit » et pourquoi.
