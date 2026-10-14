# Sprint 1 — Fondations : modèles, statuts, état persistant (SQLite)

**But :** créer la « mémoire » d'un export, indépendante du navigateur. Rien n'appelle encore l'API.
Spec : §4.4 (statuts), §5.4 (état persistant), §6.1 (stockage), §8 (sécurité).
Dépend de : sprint 0.

## En une phrase
Chaque export a un dossier sur disque et une petite base SQLite qui dit où il en est. Si tout s'arrête,
ces fichiers suffisent pour savoir quoi faire ensuite.

## Tâches
1. `bulk_export/models.py`
   - `ExportStatus` (Enum) : PENDING, RUNNING, STOPPING, PAUSED, FAILED, INCOMPLETE, VALIDATING, COMPLETED.
   - Table des **transitions autorisées** (ex. COMPLETED n'est atteignable que depuis VALIDATING).
     Toute transition interdite lève une erreur explicite.
   - `ExportConfig` (dataclass figée `frozen=True`) : filtres, période, marques, format, `batch_size`
     (10k / 25k par défaut / 50k), `rows` (1 000 par défaut, plafonné par la valeur confirmée au sprint 0),
     `random=False` imposé, nom de configuration.
   - `config_hash` : SHA-256 d'une sérialisation JSON **triée** de la config (même config = même empreinte).
   - Import/export JSON de la config (parcours « Import JSON » de la spec). Refuser tout champ ressemblant à un secret.
2. `bulk_export/paths.py` (ou dans `models.py`) : racine via `BULK_EXPORT_DIR` (défaut `./exports`),
   création de `exports/{export_id}/batches/` et `output/`. `export_id` = horodatage + suffixe aléatoire,
   validé par une regex (empêche `../` et l'accès au dossier d'un autre export).
3. `bulk_export/state_store.py` — SQLite (`checkpoints.sqlite`), mode WAL, `synchronous=FULL` :
   - Table `export_state` : tous les champs de la spec §5.4 (+ `created_at`, `finished_at`, `pages_count`,
     `stop_requested`).
   - Table `pages` : n° de page, curseur envoyé, curseur reçu, nb de lignes, nb nouveaux, nb doublons, lot cible, horodatage.
   - Table `batches` : n° de lot, chemin, nb de lignes, SHA-256, statut (OPEN / CLOSED / VALIDATED).
   - Table `seen_ids` : `id` (clé primaire), `content_hash`, `batch_index`.
   - Table `conflicts` : id, ancien hash, nouveau hash, page, horodatage.
   - Table `events` : journal court pour l'onglet Monitor (niveau, message, horodatage).
   - Fonction `commit_page(...)` : **une seule transaction** qui insère les IDs, la ligne `pages`,
     met à jour les compteurs et `last_committed_cursor`. Elle ne doit être appelée qu'après écriture durable du fichier (sprint 3).
   - Verrou persistant « un seul export actif » (table `lock` ou fichier lock) pour la V1.
4. `bulk_export/logging_utils.py` : logger vers `export.log` avec **filtre de masquage** des tokens
   (valeurs issues des secrets + motifs type `Bearer …`, `token=…`).

## Tests (`tests/test_models.py`, `tests/test_state_store.py`)
- Transitions valides / invalides ; impossible d'aller vers COMPLETED sans VALIDATING.
- Même config → même hash ; config modifiée → hash différent.
- `commit_page` est atomique : simuler une exception au milieu → rien n'est enregistré.
- Réouverture de la base après fermeture : état identique.
- `export_id` malicieux (`../x`) refusé.
- Un faux token injecté dans un message de log n'apparaît pas dans `export.log`.

## Ne pas faire
- Pas d'appel API, pas d'interface Streamlit.

## Définition de terminé
- [ ] Tous les tests passent, anciens compris.
- [ ] `JOURNAL.md` explique en français simple le rôle de chaque table.
