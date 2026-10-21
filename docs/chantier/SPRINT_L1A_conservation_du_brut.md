# Lot 1A — Conserver le brut en base et les fichiers dans Storage

**But :** un export validé ne perd plus rien. Les mentions brutes restent dans `bulk_export.raw_mentions`
et les fichiers restent dans Storage, tant que l'utilisateur ne décide pas autrement.
**Dépend de :** sprint 6 (validation, rétention) et du correctif Excel / plat du 19/10/2026.
**Décision :** validée par l'utilisateur le 21/10/2026 (chantier « gardening », lot 1). Elle **remplace** la tâche 4
du sprint 6 (« après COMPLETED, supprimer les lignes `raw_mentions` ») et la ligne « Rétention » du tableau
d'`ADAPTATION_SUPABASE.md` §2. À consigner dans `docs/bulk_v2/decision_conservation_brut.md` (nouveau)
et dans `JOURNAL.md`.

## Pourquoi
- Aujourd'hui, `finalize.py` appelle `ss.purge_raw_mentions()` dès qu'un export passe COMPLETED, puis
  `apply_retention()` (lancée à chaque ouverture de la page, `module4_bulk_export_v2.py` ~l. 506) supprime
  les fichiers Storage après `retention_days` (30 par défaut). Au bout d'un mois, il ne reste rien.
- Le format plat lu par Compass n'est **pas** une copie complète : `postprocess_reviews()` retire
  `content origin` (texte en langue d'origine) et ramène la date au 1er du mois. Le brut est la seule
  source complète pour les analyses (lot 4 : table de verbatims commune).
- Mesure d'urgence déjà demandée à l'utilisateur : `retention_days = 3650` dans les Secrets.

## Tâches
1. **Purge optionnelle** — `bulk_export/settings.py` : nouveau paramètre `purge_raw_after_validation`
   (booléen, **faux par défaut**, secret `[bulk_export] purge_raw_after_validation`, variable
   `BULK_EXPORT_PURGE_RAW`). `finalize.py` : n'appeler `purge_raw_mentions()` que s'il est vrai ;
   sinon, ajouter l'événement « Mentions conservées en base (purge désactivée) ».
   `purge_raw_mentions()` elle-même ne change pas (elle reste utilisable à la main).
2. **Rétention « jamais »** — `retention_days = 0` doit signifier « ne jamais supprimer les fichiers ».
   ⚠ Aujourd'hui, 0 ferait l'inverse : `exports_with_expired_files()` sélectionne
   `finished_at < now() - 0 jour`, donc **tous** les exports. `apply_retention()` ne fait rien si
   `retention_days <= 0` ; une valeur négative est refusée par `load_settings()`. Nouveau défaut : `0`.
3. **Index pour le lien avec Compass** — migration `bulk_export/migrations/004_conservation.sql`
   (rejouable, dans une transaction, comme 003) : index sur `raw_mentions (compass_id)`.
   Il servira au lot 4 (retrouver le brut d'un verbatim Compass).
4. **Surveillance de l'espace disque** — le brut conservé grossit à chaque export (≈ 1 Go par export de
   500 000 mentions selon l'estimation de la spec, à mesurer). Onglet Export History :
   - pour chaque export : « Brut en base : conservé » ou « effacé le … » (colonne `raw_purged_at`) ;
   - en haut de l'onglet : taille de la base (`pg_database_size`) et de `raw_mentions`
     (`pg_total_relation_size`), avec un avertissement au-delà d'un seuil réglable
     `alerte_taille_base_go` (défaut 6, pour 8 Go inclus dans le plan Pro).
5. **Réhydratation (P1, après 1 à 4)** — les exports déjà purgés dont les lots JSONL sont encore dans
   Storage peuvent retrouver leur brut. Commande `python -m bulk_export.rehydrate <export_id>` :
   - refuse si l'export n'est pas COMPLETED, si `raw_purged_at` est vide, ou si ses fichiers ont expiré ;
   - relit chaque `batch_*.jsonl.gz` en flux, vérifie son empreinte (`files.sha256` et `content_sha256`) ;
   - recalcule les empreintes avec `fingerprints.compute()` et les **mêmes réglages que l'export**
     (`config_json`) ; `raw_json` est réinséré tel quel ; `seq` = ordre de lecture ;
     `page_no` n'est pas dans les lots : mettre `0` et le documenter (« réhydraté ») ;
   - tout dans une transaction : le nombre de lignes doit être égal à `unique_count` et chaque `mention_id`
     doit être unique, sinon rien n'est enregistré ;
   - à la fin : `raw_purged_at = NULL` et un événement « Brut réhydraté depuis les lots (N mentions) ».
   Un bouton « Réhydrater » dans Export History est optionnel (P2).

## Hors périmètre
- Toute modification de `module3_bulk_export.py` (règle n°1).
- L'import dans Compass (`SPRINT_L1B`, dépôt `mvp_verbatim_import`).
- Archivage du brut ancien hors de la base : à décider quand l'avertissement de taille se déclenchera.

## Tests
- Purge désactivée (défaut) : après COMPLETED, `raw_mentions` contient `unique_count` lignes ;
  `raw_purged_at` reste vide.
- Purge activée : comportement actuel inchangé (tests existants).
- `retention_days = 0` : aucun fichier supprimé, même pour un export terminé depuis longtemps ;
  `retention_days = -1` : erreur de configuration explicite ; `retention_days = 30` : comportement actuel.
- Réhydratation : export purgé → réhydraté → mêmes `mention_id`, `content_key`, `compass_id` qu'avant la
  purge (comparer sur un faux export `fake_*`) ; lot altéré d'un octet → refus, rien en base.
- Tous les tests existants restent verts (284 au 19/10/2026).

## À faire par l'utilisateur
- Exécuter `004_conservation.sql` dans le SQL Editor de Supabase (après 001 à 003), comme indiqué dans `LISEZMOI.md`.
- Secrets `[bulk_export]` : `retention_days = 0` (remplace 3650) ; laisser `purge_raw_after_validation`
  absent (= faux).
- Mettre à jour le tableau des scripts de `LISEZMOI.md` (ligne 004).

## Définition de terminé
- [ ] Un export lancé après ce sprint garde son brut en base le lendemain.
- [ ] Les exports purgés encore réhydratables l'ont été (liste dans `JOURNAL.md`).
- [ ] Tous les tests passent ; `JOURNAL.md` et `decision_conservation_brut.md` à jour.
- [ ] Un commit sur une nouvelle branche partant de `main` (la fusion de `feature/bulk-export-v2` dans `main`
      est faite au lot 0), puis une pull request.
