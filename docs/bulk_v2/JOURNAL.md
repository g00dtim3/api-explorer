# Journal du projet Bulk Export V2

## Sprint 0 — Audit (en cours, 14/10/2026)

### Fait
- Branche `feature/bulk-export-v2` créée.
- `docs/bulk_v2/audit_code.md` : audit complet du code existant (client API, boucle du module 3,
  `build_filter_params`, `postprocess_reviews` transformation par transformation, téléchargements, dépendances).
- `docs/bulk_v2/audit_api.md` : rédigé à partir de la documentation fournisseur v2.0 (mars 2025), transmise par
  l'utilisateur le 15/10/2026 (PDF non commité).
- `docs/bulk_v2/questions_fournisseur.md` : 17 questions, réduites aux points que la documentation ne règle pas
  (question « Hébergement » retirée).
- `.gitignore` ajouté (secrets, exports, données réelles).

### Décisions
- **Pas de script `scripts/audit_api.py`** : l'utilisateur dispose déjà des mesures de l'API. Pas de tests pour ce
  sprint, puisqu'aucun code n'est écrit.
- Statut « documenté » ajouté dans `audit_api.md` : écrit par le fournisseur, mais pas encore vérifié en pratique.
- Règle de fin de pagination **provisoire et configurable** (`audit_api.md` §5), car la documentation ne la décrit pas.
- Le moteur ne supposera aucune liste figée de champs : seul `id` est obligatoire (écart C entre la documentation et le code).
- `ADAPTATION_SUPABASE.md` fait foi sur `SPEC.md` / `CLAUDE.md` pour le stockage (Postgres + Storage, pas SQLite local).

### Points ouverts (à traiter dans les sprints suivants)
1. 🔴 Token visible dans les messages d'erreur (`api_client.py:42` et `:47`) : masquage indispensable en V2.
2. 🔴 Pas de timeout, erreurs muettes (`{}`), cache `st.cache_data` de 1 h, erreurs comprises : la V2 a besoin
   d'un appel `/reviews` sans cache et aux erreurs structurées, ajouté sans changer `fetch()`.
3. 🟠 Le token n'est lisible que via `st.secrets` : prévoir une variable d'environnement pour le mode ligne de commande.
4. 🟠 `pandas>=2.0.0` sans borne haute ; pandas 3 supprime `applymap` (modules 2 et 3). À décider : figer la
   version ou laisser en l'état (hors périmètre « ne pas modifier le module 3 »).
5. 🟠 `postprocess_reviews()` : réservé au format analytique ; lecture des attributs fragile, perte du jour de la date.
6. 🔴 **Quota** : seul `/reviews` consomme du quota, au nombre de mentions renvoyées. Un export de 500 000 en
   consomme au moins 500 000, et chaque relecture de page reconsomme. Il faut vérifier le quota réel (`/quotas`) :
   l'exemple de la documentation montre 100 000. Le contrôle « quota restant ≥ volume attendu » sera obligatoire
   avant tout lancement.
7. Inconnus à faire confirmer : signal de fin, ordre stable, validité du curseur, limites de débit / `Retry-After`,
   format des erreurs, stabilité des données, unicité de `id`, format des dates (`YYYY-DD-MM` dans le texte,
   `YYYY-MM-DD` dans les exemples), liste à jour des champs.
8. Volumétrie (taille d'une mention, temps par page) : non mesurable sans appel réel. À mesurer automatiquement
   dès la première page d'un vrai export (sprint 1). Seul chiffre certain : 500 pages minimum pour 500 000 mentions.

### Définition de terminé du sprint 0
- [x] `audit_code.md` et `audit_api.md` existent et sont lisibles par un non-développeur.
- [~] Champ ID natif identifié : `id` (documenté). Présence sur 100 % des mentions : **non vérifiée**.
- [~] Règle de fin de pagination : **non documentée**. Règle provisoire configurable proposée.
- [x] Liste complète des transformations de `postprocess_reviews()`.
- [ ] Estimation chiffrée de l'espace et de la durée : **impossible sans mesure réelle**. Formules prêtes, mesure au sprint 1.
- [x] Aucun token ni mention réelle commité.

### Action humaine
- Envoyer `questions_fournisseur.md` au fournisseur ; vérifier le quota réel dans l'onglet quotas de l'application.
