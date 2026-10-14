# Sprint 4 — Worker indépendant du navigateur et reprise

**But :** que l'export continue même si on ferme l'onglet, et qu'on puisse le reprendre après un arrêt du serveur.
Spec : §5.6, §5.4, §4.3 (Stop after current batch).
Dépend de : sprint 3.

## En une phrase
Streamlit ne fait plus le travail : il dépose une demande, et un programme séparé (le « worker ») l'exécute.

## Décision humaine préalable (à noter dans `JOURNAL.md`)
Où tournent le worker et le dossier `BULK_EXPORT_DIR` ? Il faut un disque **persistant**
(serveur, VM, poste local). Un hébergement à disque éphémère ne permet pas la reprise : le signaler et ne pas le promettre.

## Tâches
1. `bulk_export/jobs.py` — file d'attente persistante simple (SQLite globale `BULK_EXPORT_DIR/jobs.sqlite`) :
   `submit(config) -> export_id`, `request_stop(export_id)`, `request_resume(export_id)`, `list_exports()`.
   Écrit `config.json` (sans secret) et passe l'export en PENDING.
2. `bulk_export/worker.py` — lancé avec `python -m bulk_export.worker` :
   - Boucle : prend le prochain export PENDING (ou reprise demandée), pose le verrou, lance `ExportEngine.run`.
   - **Battement de cœur** (`heartbeat_at`) mis à jour régulièrement.
   - Au démarrage : tout export resté RUNNING/STOPPING avec un battement trop ancien est considéré
     interrompu → passé en PAUSED (reprenable), événement journalisé.
   - Arrêt propre sur SIGTERM/SIGINT : demande d'arrêt après la page en cours.
   - Le token est lu dans l'environnement / secrets, jamais écrit sur disque.
3. Supervision : fournir un exemple prêt à l'emploi selon l'hébergement choisi
   (`deploy/bulk-export-worker.service` systemd, ou commande `supervisord`, ou procédure manuelle documentée).
4. Option « démarrer le worker depuis Streamlit » si aucun worker ne répond (processus détaché), clairement signalée
   comme solution de dépannage.

## Tests (`tests/test_worker.py`)
- Soumission → le worker traite l'export jusqu'à INCOMPLETE (avec `fake_api_client`).
- Deux soumissions → traitées l'une après l'autre, jamais en même temps.
- Arrêt demandé → PAUSED après la page en cours ; reprise → résultat identique à un export sans arrêt.
- Worker tué brutalement (processus réel, `kill -9`) puis relancé → export repris sans perte ni doublon.
- Verrou périmé (worker mort) → libéré au démarrage suivant.

## Définition de terminé
- [ ] Tous les tests passent, anciens compris.
- [ ] Procédure de lancement du worker écrite en français simple dans `docs/bulk_v2/WORKER.md`.
- [ ] Décision d'hébergement consignée dans `JOURNAL.md`.
