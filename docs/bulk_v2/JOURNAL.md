# Journal du projet Bulk Export V2

## Sprint 0 — Audit (en cours, 14/10/2026)

### Fait
- Branche `feature/bulk-export-v2` créée.
- `docs/bulk_v2/audit_code.md` : audit complet du code existant (client API, boucle du module 3,
  `build_filter_params`, `postprocess_reviews` transformation par transformation, téléchargements, dépendances).
- `docs/bulk_v2/audit_api.md` : squelette, en attente des mesures de l'utilisateur.
- `docs/bulk_v2/questions_fournisseur.md` : brouillon (question « Hébergement » retirée).
- `.gitignore` ajouté (secrets, exports, données réelles).

### Décisions
- **Pas de script `scripts/audit_api.py`** : l'utilisateur dispose déjà des mesures de l'API. Pas de tests pour ce
  sprint, puisqu'aucun code n'est écrit.
- `ADAPTATION_SUPABASE.md` fait foi sur `SPEC.md` / `CLAUDE.md` pour le stockage (Postgres + Storage, pas SQLite local).

### Points ouverts (à traiter dans les sprints suivants)
1. 🔴 Token visible dans les messages d'erreur (`api_client.py:42` et `:47`) : masquage indispensable en V2.
2. 🔴 Pas de timeout, erreurs muettes (`{}`), cache `st.cache_data` de 1 h, erreurs comprises : la V2 a besoin
   d'un appel `/reviews` sans cache et aux erreurs structurées, ajouté sans changer `fetch()`.
3. 🟠 Le token n'est lisible que via `st.secrets` : prévoir une variable d'environnement pour le mode ligne de commande.
4. 🟠 `pandas>=2.0.0` sans borne haute ; pandas 3 supprime `applymap` (modules 2 et 3). À décider : figer la
   version ou laisser en l'état (hors périmètre « ne pas modifier le module 3 »).
5. 🟠 `postprocess_reviews()` : réservé au format analytique ; lecture des attributs fragile, perte du jour de la date.
6. Mesures API à reporter dans `audit_api.md` ; questions à envoyer au fournisseur.
