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

---

## Sprint 2 — Client API robuste et adaptateur de pagination (15/10/2026)

### Fait
| Fichier | Rôle |
|---|---|
| `bulk_export/api_http.py` | Appel HTTP **sans cache**, avec délais maximaux (10 s pour la connexion, 120 s pour la lecture). Chaque erreur est une exception typée : accès refusé, trop de requêtes, panne passagère, requête refusée, réponse mal formée. L'adresse appelée, qui contient le token, n'est jamais affichée. Mesure le temps de réponse et la taille de chaque page. |
| `bulk_export/retry.py` | Nouvelles tentatives limitées (5), avec un délai qui double plus une part de hasard, et le respect de `Retry-After` (plafond de 5 min). Aucune nouvelle tentative sur un accès refusé ou une réponse mal formée. |
| `bulk_export/api_adapter.py` | Contrat générique (`PageResult`, `PaginationAdapter`) et version Ratings & Reviews : curseur `*`, mêmes filtres pour `/metrics` et `/reviews`, `random` jamais envoyé, règle de fin réglable, plafond de pages calculé |
| `bulk_export/settings.py` | Lecture du token de l'API : `[api] token` (comme l'application) ou `BULK_EXPORT_API_TOKEN` |
| `bulk_export/models.py` | Réglages de pagination figés dans la configuration d'export |
| `tests/` | +69 tests : faux serveur API (`tests/fake_api.py`), client HTTP, nouvelles tentatives, adaptateur, et **premier test de non-régression des modules 1 à 3** |

### Règle de fin retenue et sa source
Voir `audit_api.md` §5. **Source : déduction de l'audit et comportement du module 3. Non confirmée par le
fournisseur.** Par défaut :
- curseur identique et page vide : fin normale ;
- curseur identique avec des mentions, ou page vide avec un autre curseur : fin, avec un avertissement au journal ;
- mentions sans curseur suivant : erreur ;
- plus de pages que prévu : erreur.

Ces deux cas ambigus sont réglables (`error` au lieu de fin), et figés avec chaque export.

### Décisions
- **`api_client.py` n'est pas modifié** : sa lecture du token à l'import, son cache d'une heure et son affichage
  d'erreurs auraient dû changer, avec un risque pour les modules 1 à 3. Le nouveau client reprend la même adresse et
  le même encodage (environ 5 lignes dupliquées). Un test vérifie que `api_client` répond toujours exactement comme avant.
- **Pas de fonction « identifiant de mention »** dans l'adaptateur, puisque l'`id` de l'API n'est pas fiable
  (`decision_identifiant.md`). L'unicité repose sur les empreintes du sprint 1.
- Un JSON illisible avec un code 200 est traité comme une panne passagère (transfert probablement interrompu) ; un
  JSON lisible mais de forme inattendue est une erreur définitive.
- Les mentions reçues sont transmises **sans aucune modification** (test dédié).

### Tests
- `pytest` : **174 réussis** avec la base Postgres de test ; sans base, 154 réussis et 20 sautés.
- Aucun appel réel à l'API : le token n'est pas sur la machine de développement.

### Points ouverts
1. Les inconnues de l'API (nom du champ verbatim, comportement réel de fin, répétition des `id`, taille et temps par
   page) seront mesurées au **premier export réel** (sprint 3). Les mesures sont prêtes dans `PageResult.raw_meta`.
2. Le plafond de 5 minutes pour `Retry-After` est un choix par défaut, à ajuster si l'API impose des pauses plus longues.
3. Points ouverts du sprint 1 toujours valables (origine du fichier Compass, mise à jour de `CLAUDE.md`).

---

## Sprint 3 — Moteur d'export : pages, tri des mentions, transaction par page (15/10/2026)

### Fait
| Fichier | Rôle |
|---|---|
| `bulk_export/dedup.py` | Tri des mentions d'une page : nouvelle, doublon, jumelle ou rejetée. Fonctions pures, les mentions ne sont jamais modifiées. |
| `bulk_export/engine.py` | `ExportEngine.run` : la boucle page par page, l'arrêt propre, les erreurs, la reprise après coupure de la base |
| `bulk_export/migrations/002_rejected.sql` | Table `rejected_mentions` (**à exécuter dans Supabase**) |
| `bulk_export/state_store.py` | Mentions rejetées enregistrées dans la même transaction que la page ; `set_expected_count` |
| `bulk_export/db.py` | `apply_all_migrations` (applique 001, 002… dans l'ordre) |
| `tests/` | +24 tests : tri sans base (8), moteur sur la base de test (16), faux serveur paginé |

### Pourquoi « une page = une transaction » protège contre les pertes et les doublons
Pour chaque page, le moteur écrit **en une seule fois** dans la base :
- les mentions nouvelles ;
- les doublons, les jumelles et les rejets ;
- la ligne de la page ;
- les compteurs ;
- **le point de reprise**, c'est-à-dire le curseur de la page suivante.

Postgres garantit qu'une transaction est enregistrée **en entier ou pas du tout**.
- **Si l'application s'arrête avant la fin de l'écriture**, rien de la page n'est en base, et le point de reprise
  pointe encore sur cette page. À la reprise, on la relit et on l'écrit : **aucune perte**.
- **Si l'arrêt survient juste après**, la page est en base avec son point de reprise, qui pointe sur la page
  suivante. À la reprise, on continue à partir de là : **aucun doublon**.
- Il n'existe **aucun moment** où le point de reprise est avancé sans les mentions, ni l'inverse. C'est la règle n°4.
- En dernier rempart, la clé de la table des mentions (`export_id` + empreinte) refuse physiquement une même mention
  deux fois. Toute la page serait alors annulée plutôt que d'enregistrer un doublon.

Cas délicat traité : la base reçoit l'ordre d'enregistrer, l'enregistre, mais la connexion coupe avant que le moteur ait
la confirmation. Le moteur se reconnecte et **regarde ce que la base contient**. Si la page y est, il passe à la
suivante ; sinon, il la réécrit. Les deux cas sont testés.

### Ce que le moteur écrit dans le journal de l'export (onglet Monitor)
- une ligne par page : mentions reçues, nouvelles, doublons, jumelles, rejetées, temps de réponse, taille ;
- à la première page de chaque lancement : **la liste des noms de champs reçus**, sans aucune valeur. C'est elle qui
  tranchera la question du champ verbatim (`verbatim content` ou `content trad`) ;
- les `id` API portés par plusieurs mentions différentes, pour vérifier sur données réelles que `id` n'est pas fiable ;
- les avertissements de la règle de fin (situations ambiguës acceptées), les coupures, les arrêts et les reprises.

### Décisions
- **Mentions sans date** : ni jetées, ni enregistrées comme valides. Elles sont gardées telles quelles dans
  `rejected_mentions`, comptées dans `error_count`, et empêcheront COMPLETED à la validation (sprint 6).
- **Tests sur une vraie base Postgres** plutôt qu'une fausse base en mémoire, pour ne pas reproduire la logique de la
  base en double. Le tri reste testé seul, sans base.
- Le moteur **prend lui-même le bail** au démarrage et le **libère** à la fin ; il le renouvelle après chaque page
  et s'arrête net s'il l'a perdu.
- Fin de pagination → INCOMPLETE ; erreur → FAILED avec le numéro de page et un message masqué. Les deux sont
  reprenables depuis le dernier point de reprise.
- Le volume `/metrics` est demandé **une seule fois**, au premier lancement, puis figé.
- Vérification de la solidité des tests : deux mécanismes de protection ont été volontairement cassés (reprise après
  coupure, détection des doublons). Les tests l'ont bien détecté, puis le code a été remis en état.

### Tests
- `pytest` : **199 réussis** avec la base Postgres de test ; sans base, les tests base de données sont sautés.

### Points ouverts
1. **À faire par vous : exécuter `002_rejected.sql` dans Supabase** (LISEZMOI §1.3).
2. Le premier export réel arrivera avec le lancement en ligne de commande (sprint 4) ou l'interface (sprint 5).
3. Points ouverts précédents inchangés (origine du fichier Compass, mise à jour de `CLAUDE.md`).

---

## Sprint 4 — Exécution en arrière-plan, bail et reprise (15/10/2026)

### Fait
| Fichier | Rôle |
|---|---|
| `bulk_export/runner.py` | Gestionnaire d'exécution : tâche de fond, battement de cœur du bail, arrêt (drapeau en base), reprise, détection des orphelins, reprise automatique optionnelle, erreur imprévue → FAILED |
| `bulk_export/run.py` | Ligne de commande : `--create`, `--export-id`, `--status`, `--recover` ; Ctrl+C = arrêt propre ; secrets uniquement par variables d'environnement |
| `bulk_export/state_store.py` | `recover_orphans` (RUNNING/STOPPING sans bail valide → PAUSED + événement), `active_export_id` |
| `bulk_export/settings.py` | Option `auto_resume` (désactivée par défaut) ; `http://` autorisé uniquement vers 127.0.0.1/localhost (faux serveur des tests) |
| `docs/bulk_v2/EXECUTION.md` | Ce qui arrête un export, ce qui ne l'arrête pas, comment reprendre |
| `tests/` | +12 tests : gestionnaire (9), et vrais processus : `kill -9`, Ctrl+C, paramètres manquants (3) |

### ⚠️ Limite assumée de la V1
**L'export s'arrête si l'application Streamlit redémarre, est redéployée ou est mise en veille.** C'est la limite
notée dans `ADAPTATION_SUPABASE.md` §4, faute de serveur dédié. **Aucune donnée enregistrée n'est perdue** :
l'export est reconnu comme interrompu (2 minutes au plus), passe en PAUSED et se reprend d'un clic, ou tout seul si
`auto_resume = true`. Un worker indépendant de l'application (GitHub Actions) reste possible au sprint 8 optionnel,
grâce à la ligne de commande.

### Décisions
- **Battement de cœur** (écart avec le fichier du sprint, validé) : le bail dure 2 minutes et il est prolongé toutes
  les 30 secondes par une tâche séparée, y compris pendant les longues attentes de l'API. Sans cela, une page lente
  aurait fait passer à tort un export vivant pour un orphelin. Un test le vérifie : il échoue bien si on retire le
  battement.
- Le gestionnaire prend le bail **avant** de lancer la tâche de fond : la réponse « lancé » ou « refusé » est
  immédiate et fiable.
- Le drapeau d'arrêt est écrit **en base** : un arrêt demandé depuis un autre onglet, ou après un rechargement,
  est bien pris en compte.
- La ligne de commande ne prend **aucun secret en argument** (rien dans l'historique du terminal).

### Test de résistance sur de vrais processus
Le test lance `python -m bulk_export.run` contre un faux serveur API local, puis :
1. le tue avec `kill -9` après 4 pages ;
2. vérifie que rien n'est touché tant que le bail court ;
3. vérifie qu'après expiration, l'export est reconnu orphelin et passe en PAUSED ;
4. le reprend en ligne de commande.

Résultat : **mêmes 60 mentions, même ordre, zéro doublon** qu'un export sans interruption.

### Tests
- `pytest` : **211 réussis** avec la base Postgres de test.

### Points ouverts
1. Le **premier export réel** est possible dès maintenant en ligne de commande (`EXECUTION.md`), ou au sprint 5 depuis
   l'application.
2. Rappel : `002_rejected.sql` doit être exécuté dans Supabase avant tout export réel.
3. Points ouverts précédents inchangés (origine du fichier Compass, mise à jour de `CLAUDE.md`).

---

## Sprint 5 — Interface Streamlit : New Export et Export Monitor (15/10/2026)

### Fait
| Fichier | Rôle |
|---|---|
| `module4_bulk_export_v2.py` | Page « Bulk Export V2 » : onglets New Export, Export Monitor, Downloads (squelette), Export History (liste) |
| `bulk_export/ui_logic.py` | Règles sans affichage : filtres via `build_filter_params`, import JSON (format V2 et ancien format), estimation, blocages, progression |
| `main_app.py` | Entrée de menu « 🧱 Bulk Export V2 », chargée à part (un problème du module 4 n'empêche pas les autres de fonctionner). Rien d'autre ne change. |
| `tests/test_ui_logic.py`, `tests/test_app_smoke.py` | +19 tests, dont 4 tests de la page avec l'outil de test de Streamlit |

### Ce que fait la page
- **New Export** : filtres du formulaire (mêmes listes et même `build_filter_params` que le module 1) ou import JSON
  (format V2 ou ancien format ; secrets refusés ; sélection de produits ignorée avec un avertissement). Mode Aperçu
  (100 mentions, rien d'enregistré, avec la liste des champs reçus), formats, taille des lots, export de la
  configuration. « Estimer » donne le volume, les pages et les lots. **Durée et espace seulement s'il existe des
  mesures réelles** (exports précédents), sinon rien. « Voir les quotas ».
- **Lancement bloqué** si : Supabase injoignable, token absent, configuration invalide, pas d'estimation **pour ces
  filtres-là**, volume nul, ou un export déjà en cours. Avertissement au-delà de 500 000 mentions. L'encadré de la
  limite V1 est toujours visible.
- **Export Monitor** : indicateurs de la spec §4.3 relus dans Supabase, barre de progression plafonnée (écart affiché),
  rafraîchissement automatique toutes les 5 s pendant une collecte (seul ce bloc est rafraîchi), 20 derniers
  événements (erreurs en rouge, avertissements en orange), boutons « Arrêter après la page en cours » et
  « Reprendre ». Un export orphelin est détecté et repassé en PAUSED.
- À chaque ouverture de la page, les exports interrompus sont détectés (et relancés si `auto_resume = true`).

### Décisions
- Les listes de référence (marques, pays…) passent par le **client strict** du sprint 2, et non par `api_client` :
  en cas d'erreur, l'ancien client affiche l'adresse complète, token compris.
- Navigation entre onglets par un sélecteur horizontal plutôt que `st.tabs`, pour pouvoir **basculer
  automatiquement vers le Monitor** après « Lancer ».
- Le volume affiché par l'estimation est **celui enregistré** dans l'export (pas de second appel à `/metrics`).
- **Bug trouvé par les tests et corrigé** : le bouton « Estimer » et l'estimation enregistrée partageaient la même clé,
  ce qui faisait planter la page après un clic.

### Tests
- `pytest` : **230 réussis** avec la base de test (181 réussis et 49 sautés sans base).
- Les tests de la page vérifient :
  - le message clair sans Supabase ;
  - l'affichage du Monitor ;
  - le blocage du lancement sans estimation ;
  - le parcours complet « estimer → lancer → bascule vers le Monitor → export jusqu'à INCOMPLETE » ;
  - le chargement des 5 entrées du menu principal.

### Vérifications manuelles sur Streamlit Cloud (à faire par vous — résultats à reporter ici)
| # | Vérification | Résultat attendu | Résultat constaté |
|---|---|---|---|
| 1 | Déployer la branche, secrets en place, scripts 001 et 002 exécutés | La page « Bulk Export V2 » s'ouvre sans erreur | _à compléter_ |
| 2 | Petit export réel (quelques milliers de mentions) | Il va jusqu'à INCOMPLETE ; le journal montre « Champs reçus : … » | _à compléter_ |
| 3 | Recharger la page pendant l'export | L'export continue, l'affichage revient | _à compléter_ |
| 4 | Arrêter, puis reprendre | PAUSED après la page en cours, puis reprise jusqu'au bout | _à compléter_ |
| 5 | « Reboot app » pendant un export | Export affiché comme interrompu (≤ 2 min) → Reprendre → fin sans perte ni doublon (doublons = 0) | _à compléter_ |

### Points ouverts
1. Les 5 vérifications ci-dessus, et la ligne « Champs reçus » du premier export réel.
2. Downloads (fichiers CSV / JSONL / ZIP, manifeste) et validation (COMPLETED) : sprint 6.
3. Points ouverts précédents inchangés (origine du fichier Compass, mise à jour de `CLAUDE.md`).
