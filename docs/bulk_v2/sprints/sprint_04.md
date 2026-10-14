# Sprint 4 — Exécution en arrière-plan, bail et reprise

**But :** que l'export avance sans bloquer la page, ne tourne jamais en double, et puisse être repris sans perte
après un redémarrage de Streamlit Cloud.
Spec : §5.6, §5.4, §4.3. Adaptation : §2 (ligne « Worker »), §4 (limite assumée).
Dépend de : sprint 3.

## En une phrase
L'export tourne « dans les coulisses » de l'application. Il pose un bail dans Supabase et le renouvelle :
si l'application meurt, le bail expire, et l'export devient reprenable d'un clic.

## Tâches
1. `bulk_export/runner.py`
   - Un **gestionnaire unique par processus** (créé via `st.cache_resource` côté Streamlit) qui lance
     `ExportEngine.run` dans un **thread d'arrière-plan**.
   - `start(export_id)` : prend le bail (`acquire_lease`) ; refuse si un autre export est actif.
   - Renouvellement du bail après chaque page (et au minimum toutes les N secondes pendant les attentes de retry).
   - `request_stop(export_id)` : écrit `stop_requested = true` en base (pas seulement en mémoire) → arrêt après la page en cours.
   - `resume(export_id)` : contrôles (statut reprenable, `config_hash` inchangé, bail libre ou expiré) puis relance.
   - Le thread ne touche jamais à `st.session_state` ni aux widgets Streamlit.
   - Gestion d'exception globale : toute erreur inattendue → FAILED + événement, jamais un thread mort silencieux.
2. **Détection des exports orphelins** (au chargement de la page et à chaque rafraîchissement du Monitor) :
   export en RUNNING/STOPPING dont le bail a expiré → passé en **PAUSED** avec l'événement
   « Interrompu par un redémarrage de l'application — reprenable ».
3. **Reprise automatique (option, désactivée par défaut)** : paramètre `auto_resume`. Si activé, un export orphelin
   est relancé automatiquement quand quelqu'un ouvre la page.
4. `bulk_export/run.py` — lancement en ligne de commande : `python -m bulk_export.run --export-id ...`
   (même moteur, mêmes règles de bail). Sert aux tests réels et à un futur worker GitHub Actions (sprint 8).
5. `docs/bulk_v2/EXECUTION.md` : en français simple, ce qui arrête un export (redémarrage, redéploiement, mise en veille
   de l'app), ce qui ne l'arrête pas forcément (fermer l'onglet), et comment reprendre.

## Tests (`tests/test_runner.py`)
- Démarrage → l'export avance jusqu'à INCOMPLETE (faux client API).
- Deux démarrages simultanés → le second est refusé.
- Arrêt demandé → PAUSED après la page en cours.
- Intégration (schéma de test) : processus `python -m bulk_export.run` tué brutalement (`kill -9`) au milieu →
  bail expiré → détecté comme orphelin → PAUSED → reprise → résultat identique à un export sans interruption
  (mêmes IDs, aucun doublon).

## Définition de terminé
- [ ] Tous les tests passent, anciens compris.
- [ ] `EXECUTION.md` rédigé.
- [ ] La limite « l'export s'arrête si l'application redémarre » est notée dans `JOURNAL.md`.
