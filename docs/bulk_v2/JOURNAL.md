# Journal du projet Bulk Export V2

## Sprint 0 — Audit (14–15/10/2026, terminé sous réserve de validation)

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
6. ✅ **Quota** : réglé. Le compte n'a plus de limite (indiqué par l'utilisateur le 15/10/2026). Simple avertissement, pas de blocage.
9. ✅ **Identifiant** (validé le 15/10/2026) : `id` est généré par l'API à chaque export, donc non fiable. Unicité par
   empreintes SHA-256 reprises du projet Compass : `raw_hash` (mention complète sans `id`, clé d'unicité),
   `content_key` (méthode Compass, date au jour), `compass_id` (reproduction exacte de l'id Compass, date au mois,
   format analytique uniquement, pour relier les deux projets). Règle n°6 de `CLAUDE.md` réécrite.
10. 🟠 Reproduire `compass_id` exactement : le nom du champ verbatim est à vérifier sur une vraie réponse
    (`content trad` contre `verbatim content`), voir `decision_identifiant.md` §4.
7. Inconnus à faire confirmer : signal de fin, ordre stable, validité du curseur, limites de débit / `Retry-After`,
   format des erreurs, stabilité des données, unicité de `id`, format des dates (`YYYY-DD-MM` dans le texte,
   `YYYY-MM-DD` dans les exemples), liste à jour des champs.
8. Volumétrie (taille d'une mention, temps par page) : non mesurable sans appel réel. À mesurer automatiquement
   dès la première page d'un vrai export (sprint 1). Seul chiffre certain : 500 pages minimum pour 500 000 mentions.

### Définition de terminé du sprint 0
- [x] `audit_code.md` et `audit_api.md` existent et sont lisibles par un non-développeur.
- [x] Champ ID : `id` présent mais non fiable ; clé d'unicité par empreintes validée (`decision_identifiant.md`).
- [~] Règle de fin de pagination : **non documentée**. Règle provisoire configurable proposée.
- [x] Liste complète des transformations de `postprocess_reviews()`.
- [ ] Estimation chiffrée de l'espace et de la durée : **impossible sans mesure réelle**. Formules prêtes, **reportée au sprint 1** (mesure automatique sur la première page réelle).
- [x] Aucun token ni mention réelle commité.

### Action humaine
- Envoyer `questions_fournisseur.md` au fournisseur.
