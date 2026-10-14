# Sprint 1 — Fondations : schéma Supabase, statuts, configuration figée

**But :** créer la « mémoire » d'un export dans Supabase, indépendante du navigateur et des redémarrages
de Streamlit Cloud. Rien n'appelle encore l'API.
Spec : §4.4, §5.4, §8 (sécurité). Adaptation : §2, §5.
Dépend de : sprint 0.

## En une phrase
Chaque export a ses lignes dans la base Supabase, qui disent où il en est. Si l'application redémarre,
ces lignes suffisent pour savoir quoi faire ensuite.

## Tâches
1. `bulk_export/models.py`
   - `ExportStatus` (Enum) : PENDING, RUNNING, STOPPING, PAUSED, FAILED, INCOMPLETE, VALIDATING, COMPLETED.
   - Table des **transitions autorisées** (COMPLETED seulement depuis VALIDATING ; reprise possible depuis PAUSED,
     FAILED reprenable, INCOMPLETE si la pagination n'est pas terminée). Transition interdite → erreur explicite.
   - `ExportConfig` (dataclass `frozen=True`) : filtres, période, marques, format, `batch_size`
     (10k / 25k par défaut / 50k), `rows` (1 000 par défaut, plafonné par la valeur confirmée au sprint 0),
     `random=False` imposé, nom de configuration.
   - `config_hash` : SHA-256 d'une sérialisation JSON triée (même config = même empreinte).
   - Import / export JSON de la config ; refuser tout champ ressemblant à un secret.
   - `export_id` : horodatage + suffixe aléatoire, validé par regex.
2. `bulk_export/settings.py` : lecture des paramètres depuis `st.secrets["bulk_export"]` ou variables d'environnement
   (pour la ligne de commande). Message clair si un paramètre manque, **sans afficher sa valeur**.
3. `bulk_export/db.py` : connexion Postgres avec `psycopg` (v3) via la chaîne **Session pooler**,
   timeouts de connexion et de requête, réessai limité en cas de coupure. `search_path` = schéma configuré
   (`bulk_export` en prod, `bulk_export_test` en test).
4. `bulk_export/migrations/001_init.sql` — schéma `bulk_export`, RLS activé sur chaque table, aucune politique publique :
   - `exports` : tous les champs de la spec §5.4 + `name`, `config_json`, `created_at`, `finished_at`,
     `pages_count`, `stop_requested`, `lease_owner`, `lease_expires_at`, `pagination_finished` (bool), `validation_json`.
   - `pages` : export_id, n° de page, curseur envoyé, curseur reçu, nb lignes, nb nouvelles, nb doublons, horodatage.
   - `raw_mentions` : export_id, `mention_id`, `seq` (ordre d'arrivée), `raw_json` **text**, `content_hash`, n° de page.
     Clé primaire `(export_id, mention_id)` → un doublon ne peut physiquement pas être inséré deux fois.
     Index sur `(export_id, seq)`.
   - `conflicts` : export_id, mention_id, hash d'origine, nouveau hash, `raw_json` du nouveau contenu, page, horodatage.
   - `events` : journal court (niveau, message, horodatage) pour le Monitor.
   - `files` : fichiers finaux dans Storage (chemin, type, nb lignes, SHA-256, taille).
   - Script lancé **par vous** dans l'éditeur SQL Supabase (prod), et automatiquement par les tests sur `bulk_export_test`.
5. `bulk_export/state_store.py`
   - `create_export(config)`, `get_export(id)`, `list_exports()`, `set_status(id, new)` (contrôle des transitions).
   - `commit_page(...)` : **une seule transaction** qui insère les mentions nouvelles, les conflits, la ligne `pages`,
     met à jour les compteurs et `last_committed_cursor`. Si quoi que ce soit échoue, rien n'est enregistré.
   - `acquire_lease(id, owner, ttl)`, `renew_lease`, `release_lease` : un seul exécutant par export,
     et un seul export actif à la fois en V1 (verrou en base, pas en mémoire).
   - `add_event(...)` avec masquage des secrets.
6. `bulk_export/logging_utils.py` : filtre de masquage (valeurs des secrets connus + motifs `Bearer …`,
   `token=…`, `postgresql://user:motdepasse@…`).
7. `requirements.txt` : ajouter `psycopg[binary]` (et `supabase` ou `storage3` si choisi au sprint 6, pas avant).

## Tests
- Unitaires (sans réseau) : transitions valides / invalides ; impossible d'atteindre COMPLETED sans VALIDATING ;
  même config → même hash ; `export_id` malicieux refusé ; un faux token dans un message n'apparaît plus après masquage.
- Intégration (si `BULK_EXPORT_TEST_DATABASE_URL` défini, schéma `bulk_export_test`) :
  migration rejouable ; `commit_page` atomique (exception simulée au milieu → rien en base) ;
  insertion d'un ID déjà présent impossible ; bail : un second exécutant ne peut pas prendre un export déjà tenu,
  mais peut le reprendre après expiration.

## Ce que vous (humain) devez faire
- Préparer Supabase (LISEZMOI §1), puis exécuter `001_init.sql` dans l'éditeur SQL du projet.

## Définition de terminé
- [ ] Tous les tests passent, anciens compris.
- [ ] `JOURNAL.md` explique en français simple le rôle de chaque table.
- [ ] Aucune clé ni URL avec mot de passe dans le dépôt.
