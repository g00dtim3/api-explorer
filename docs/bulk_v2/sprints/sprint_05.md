# Sprint 5 — Interface Streamlit : New Export et Export Monitor

**But :** une page utilisable pour configurer, estimer, lancer, suivre, arrêter et reprendre un export.
Spec : §3, §4.1, §4.2, §4.3. Adaptation : §4 (limite à afficher).
Dépend de : sprint 4.

## En une phrase
La page lit l'état dans Supabase et envoie des ordres au moteur ; recharger le navigateur ne perd rien.

## Tâches
1. `module4_bulk_export_v2.py` : page « Bulk Export V2 », 4 onglets (Downloads et History = squelettes jusqu'au sprint 6).
2. `main_app.py` : ajouter l'entrée de menu, sans toucher aux autres.
3. **Onglet New Export**
   - Réutiliser les widgets / fonctions de filtres existants d'API Explorer.
   - Import JSON de configuration (validé, secrets refusés) et export JSON de la config courante.
   - Mode : Complet / Aperçu (100 mentions, affichage direct, rien n'est enregistré).
   - Format : CSV UTF-8, JSONL, ZIP. Taille de lots : 10k / 25k (défaut) / 50k.
   - « Estimer le volume » → `/metrics` : volume, nombre de lots, nombre de pages ; durée et espace indicatifs
     seulement à partir des mesures du sprint 0 (sinon ne rien afficher).
   - « Voir les quotas ».
   - Blocages : configuration invalide, pas d'estimation, un export déjà actif, connexion Supabase en échec.
     Avertissement si volume > 500 000.
   - Encadré permanent rappelant la limite V1 (texte d'`ADAPTATION_SUPABASE.md` §4).
   - « Lancer l'export » → création en base + démarrage via le runner → bascule vers le Monitor.
4. **Onglet Export Monitor**
   - Sélection de l'export (par défaut : l'actif ou le dernier).
   - Indicateurs de la spec §4.3, **relus depuis Supabase** à chaque rafraîchissement (pas depuis `st.session_state`).
   - Barre de progression = uniques / attendus (plafonnée à 100 %, écart affiché).
   - Rafraîchissement automatique toutes les quelques secondes (`st.fragment(run_every=…)` si la version de Streamlit
     le permet, sinon alternative documentée), en limitant le nombre de requêtes à la base.
   - 20 derniers événements ; erreurs bloquantes en rouge ; conflits signalés.
   - Boutons : « Arrêter après la page en cours », « Reprendre » (si reprenable).
   - Si l'export est orphelin (bail expiré) : message clair + bouton Reprendre.

## Tests
- Tests unitaires des fonctions non visuelles (construction de config, règles de blocage).
- Test de fumée avec `streamlit.testing.v1.AppTest` si disponible.
- Vérifier que les autres pages de l'application se chargent toujours.

## Ce que vous (humain) devez faire — sur Streamlit Cloud
1. Déployer la branche, renseigner les Secrets.
2. Lancer un petit export réel (quelques milliers de mentions).
3. Recharger la page pendant l'export → l'export continue et l'affichage revient.
4. Arrêter, puis reprendre.
5. Pendant un export, **redémarrer l'application** (menu « Reboot app ») → l'export apparaît comme interrompu → Reprendre
   → il se termine sans perte ni doublon.

## Définition de terminé
- [ ] Tous les tests passent, anciens compris.
- [ ] Les 5 vérifications manuelles ci-dessus sont décrites dans `JOURNAL.md` avec leur résultat.
