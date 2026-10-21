# Texte à ajouter à la fin de `CLAUDE.md` (api-explorer)

À copier tel quel sous la dernière section, lors du lot 0 (fusion dans `main`).

---

## Mises à jour du 21/10/2026 (chantier « gardening »)
- **Branche** : `feature/bulk-export-v2` est fusionnée dans `main`. Streamlit Cloud déploie `main`.
  Chaque nouveau sprint part d'une nouvelle branche créée depuis `main`, puis une pull request.
- **Architecture réelle** : Postgres Supabase (schéma `bulk_export`) + Supabase Storage, et non plus SQLite
  local ni `BULK_EXPORT_DIR`. `docs/bulk_v2/ADAPTATION_SUPABASE.md` fait foi pour tout ce qui concerne le stockage.
- **Conservation** (lot 1, `docs/chantier/SPRINT_L1A_conservation_du_brut.md`) : le brut reste en base après
  COMPLETED (purge désactivée par défaut) et `retention_days = 0` signifie « ne jamais supprimer les fichiers ».
- **Base partagée** : le même projet Supabase héberge Compass (schéma `public`) et, après le lot 2, Reddit
  (schéma `reddit`). Ne jamais créer, modifier ou supprimer d'objet hors du schéma `bulk_export`.
- **Lien Compass** : `compass_id` doit rester identique, au caractère près, à l'`id` calculé par
  `compass_import/core/hasher.py` (dépôt `mvp_verbatim_import`). Toute modification de l'une des deux
  méthodes se fait des deux côtés, avec le test commun (fixture `fake_export_plat`).
