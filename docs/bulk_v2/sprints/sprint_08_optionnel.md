# Sprint 8 (optionnel) — Worker GitHub Actions

**But :** rendre l'export totalement indépendant de l'application Streamlit, comme le prévoit la spec §5.6,
sans serveur à gérer. À faire seulement si la recette (sprint 7) montre que les redémarrages de Streamlit Cloud gênent.
Dépend de : sprint 7.

## En une phrase
Le bouton « Lancer » de Streamlit demande à GitHub de faire tourner l'export sur ses machines ;
Streamlit se contente d'afficher l'avancement lu dans Supabase.

## Tâches
1. `.github/workflows/bulk_export.yml` : déclenchement `workflow_dispatch` avec `export_id` en entrée ;
   installe les dépendances et exécute `python -m bulk_export.run --export-id ...`.
   Secrets (token API, URL de base, clé Supabase) dans les **secrets du dépôt GitHub**, jamais dans le fichier.
   `timeout-minutes` réglé sous la limite de durée d'une tâche GitHub ; si la durée est atteinte, l'export
   s'arrête proprement (PAUSED) et une nouvelle tâche le reprend automatiquement.
2. Dans l'interface : option « Exécuter via GitHub Actions » ; le bouton appelle l'API GitHub (jeton à droits limités
   à ce workflow, stocké dans les secrets Streamlit) ; le Monitor affiche le lien vers l'exécution.
3. Le bail Supabase empêche toujours deux exécutants sur le même export (Streamlit et GitHub).
4. `docs/bulk_v2/EXECUTION.md` mis à jour : coût en minutes GitHub, durée maximale, procédure en cas d'échec.

## Vérifications avant de lancer ce sprint (vous)
- Le dépôt est-il privé ? Combien de minutes GitHub Actions sont incluses dans votre offre ?
- L'API Ratings & Reviews accepte-t-elle des appels depuis les machines de GitHub (pas de restriction d'adresse IP) ?

## Définition de terminé
- [ ] Un export lancé depuis Streamlit s'exécute sur GitHub et se termine même si l'application Streamlit redémarre.
- [ ] Aucun secret visible dans le workflow ni dans les journaux GitHub.
- [ ] Tous les tests passent.
