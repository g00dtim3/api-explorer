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

---

## Sprint 1 — Fondations : schéma Supabase, statuts, configuration figée (15/10/2026)

### Fait
| Fichier | Rôle |
|---|---|
| `bulk_export/models.py` | Les 8 statuts et les passages autorisés ; configuration figée (`ExportConfig`) et son empreinte ; identifiant d'export |
| `bulk_export/fingerprints.py` | Les trois empreintes d'une mention (`raw_hash`, `content_key`, `compass_id`). **Avancé depuis le sprint 3**, car le schéma en dépend. |
| `bulk_export/settings.py` | Paramètres Supabase lus dans les secrets Streamlit ou les variables d'environnement ; jamais affichés |
| `bulk_export/logging_utils.py` | Masquage des secrets dans tout message |
| `bulk_export/db.py` | Connexion Postgres (délais maximaux, nouvelles tentatives, messages masqués) et application des migrations |
| `bulk_export/migrations/001_init.sql` | Création du schéma `bulk_export` et des 6 tables (RLS sans politique) |
| `bulk_export/state_store.py` | Créer, lire, changer de statut, enregistrer une page, bail, journal |
| `docs/bulk_v2/LISEZMOI.md` | Ce que vous devez faire dans Supabase et dans les secrets Streamlit |
| `tests/` | 105 tests : 85 sans base, 20 sur une vraie base Postgres |
| `requirements.txt` | Ajout de `psycopg[binary]` (seule modification d'un fichier existant) |
| `requirements-dev.txt`, `pytest.ini` | Outils de test |

### Le rôle de chaque table, en français simple
- **`exports`** : la « fiche » de chaque export. Elle contient son nom, ses filtres figés, son statut, ses compteurs
  (mentions reçues, enregistrées, doublons, collisions, erreurs), le **point de reprise** (le curseur à envoyer pour
  la page suivante) et le **bail** (qui travaille dessus, et jusqu'à quand). C'est elle que l'onglet Monitor relira.
- **`pages`** : une ligne par page de l'API enregistrée, avec le curseur envoyé, le curseur reçu et le nombre de
  mentions. Elle permet de refaire l'historique exact du parcours.
- **`raw_mentions`** : les mentions **telles que reçues** (texte JSON non modifié), avec leurs trois empreintes et
  leur ordre d'arrivée. Sa clé est (`export_id`, `raw_hash`) : une même mention ne peut **physiquement** pas être
  enregistrée deux fois. Ces lignes seront effacées une fois les fichiers finaux produits et validés.
- **`conflicts`** : les **doublons** (même mention reçue deux fois ; on note l'`id` API de la copie écartée) et les
  **collisions** (deux avis jumeaux, tous deux gardés). Aucun texte de verbatim n'y est copié.
- **`events`** : le journal court affiché dans le Monitor. Chaque message est masqué avant d'être écrit.
- **`files`** : la liste des fichiers finaux déposés dans Supabase Storage (sprint 6), avec leur empreinte SHA-256.

### Décisions
- **Une page = une transaction** (`commit_page`) : mentions, doublons et collisions, ligne de page, compteurs et
  point de reprise sont écrits ensemble, ou pas du tout. Un test simule une panne au milieu : rien n'est écrit.
- `commit_page` refuse aussi une page qui n'est pas la suivante attendue, un curseur qui n'est pas le dernier point
  de reprise, et un exécutant qui a perdu son bail.
- **COMPLETED est verrouillé deux fois** : par la table des transitions (uniquement depuis VALIDATING) et en base
  (il faut une validation enregistrée avec `passed = true`).
- **Bail** : un seul exécutant par export, et un seul export actif à la fois. Un verrou Postgres empêche deux prises
  de bail simultanées. Les heures viennent de la base, pas de la machine.
- **Empreinte de la configuration** : à la relecture, si la configuration stockée ne correspond plus à son
  empreinte, l'export est refusé.
- Le fichier SQL nomme explicitement le schéma (`bulk_export.exports`…) ; les tests l'exécutent dans
  `bulk_export_test` en remplaçant ce nom.
- `compass_id` est vérifié contre le vrai code Compass (voir `decision_identifiant.md` §4) ; correction de la doc : si
  le champ verbatim manque, Compass refuse le fichier (il ne calcule pas un verbatim vide).

### Tests
- `pytest` : **105 réussis** avec une base Postgres 16 locale (`BULK_EXPORT_TEST_DATABASE_URL`) ; sans base,
  85 réussis et 20 sautés.
- Il n'existait aucun test avant ce sprint. Les modules 1 à 3 ne sont pas modifiés.
- **Non testé ici : Supabase lui-même** (pooler, rôles `anon` / `authenticated`, éditeur SQL). C'est à vérifier par
  vous en suivant `LISEZMOI.md`.

### Points ouverts
1. 🟠 **Origine du fichier que Compass importe** : Compass exige une colonne `sampling`, alors que le format plat
   produit `Sampling`. Il ne lit donc pas ce format tel quel. Si son fichier source contient la date au jour,
   `compass_id` devra utiliser le jour (simple réglage). À confirmer avant de relier les deux projets.
2. Le nom réel du champ verbatim (`verbatim content` ou `content trad`) reste à vérifier sur une vraie réponse ;
   les deux sont réglables.
3. `CLAUDE.md` décrit encore l'ancienne architecture (SQLite local, `BULK_EXPORT_DIR`) ; `ADAPTATION_SUPABASE.md`
   fait foi. Mise à jour de `CLAUDE.md` à décider.
4. Mesure de la taille d'une mention et du temps par page (reportée du sprint 0) : sprint 2 ou 3, dès le premier
   appel réel.

### Action humaine
- Suivre `docs/bulk_v2/LISEZMOI.md` §1 : vérifier la région UE, exécuter `001_init.sql`, renseigner `[bulk_export]`
  dans les secrets Streamlit.
