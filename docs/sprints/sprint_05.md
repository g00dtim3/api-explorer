# Sprint 5 — Interface Streamlit : New Export et Export Monitor

**But :** une page utilisable pour configurer, estimer, lancer, suivre, arrêter et reprendre un export.
Spec : §3, §4.1, §4.2, §4.3.
Dépend de : sprint 4.

## En une phrase
La page ne fait que lire l'état sur disque et envoyer des ordres au worker ; recharger le navigateur ne perd rien.

## Tâches
1. `module4_bulk_export_v2.py` : page « Bulk Export V2 », 4 onglets (Downloads et History restent des
   squelettes « bientôt disponible » jusqu'au sprint 6).
2. `main_app.py` : ajouter l'entrée de menu, sans toucher aux autres entrées.
3. **Onglet New Export**
   - Réutiliser les widgets / fonctions de filtres existants d'API Explorer.
   - Import JSON de configuration (validé, secrets refusés) et export JSON de la config courante.
   - Mode : Complet / Aperçu (100 mentions, sans worker, affichage direct).
   - Format : CSV UTF-8, JSONL, ZIP. Taille de lots : 10k / 25k (défaut) / 50k.
   - Bouton « Estimer le volume » → `/metrics` : volume, nombre de lots, nombre de pages, durée indicative
     seulement si mesurée (sinon ne rien afficher).
   - Bouton « Voir les quotas ».
   - Blocages : configuration invalide, pas d'estimation faite, un export déjà actif.
     Avertissement si volume > 500 000.
   - « Lancer l'export » → `jobs.submit()`, affiche l'`export_id`, bascule vers le Monitor.
4. **Onglet Export Monitor**
   - Sélection de l'export (par défaut : l'actif ou le dernier).
   - Indicateurs de la spec §4.3, **relus depuis SQLite** à chaque rafraîchissement (pas depuis `st.session_state`).
   - Barre de progression = uniques / attendus (plafonnée à 100 %, écart affiché).
   - Rafraîchissement automatique (ex. `st.fragment(run_every=…)` ou équivalent selon la version installée).
   - 20 derniers événements, erreurs bloquantes en rouge, conflits signalés.
   - Boutons : « Arrêter après la page en cours », « Reprendre » (si PAUSED / FAILED reprenable).
   - Alerte si le worker ne donne plus signe de vie.

## Tests
- Tests unitaires des fonctions non visuelles (construction de config, règles de blocage).
- Test de fumée : la page s'importe et s'exécute avec `streamlit.testing.v1.AppTest` si disponible.
- Vérifier que les autres pages de l'application se chargent toujours.

## Ce que vous (humain) devez faire
- Tester visuellement : lancer un petit export réel, recharger la page en cours, arrêter, reprendre.

## Définition de terminé
- [ ] Tous les tests passent, anciens compris.
- [ ] Recharger le navigateur pendant un export n'affecte ni l'export ni l'affichage.
- [ ] Captures ou description du test visuel dans `JOURNAL.md`.
