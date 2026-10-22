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

### Premier export réel (15/10/2026) — « Avene - FR - 26 », `exp_20261015T130315Z_0d8b9e65`
| Mesure | Valeur |
|---|---|
| Attendues (`/metrics`) / reçues / uniques | 3 165 / 3 165 / 3 164 |
| Doublons / jumelles / rejetées | 1 / 970 / 0 |
| Pages | 5 (4 avec données + 1 page vide de fin, même curseur) |
| Durée | 23 s, soit ≈ 3,5 à 4 s par page enregistrée |
| Statut | INCOMPLETE : **normal**, la validation (→ COMPLETED) arrive au sprint 6 |

**Ce que cet export a appris :**
1. **Champs réels** : `content trad` et `content origin` sont présents, `verbatim content` est absent. La documentation
   fournisseur est en retard sur l'API.
2. 🔴 **Les 970 « jumelles » sont un faux signal.** `content_key` utilise par défaut le champ `verbatim content`, qui
   n'existe pas : le verbatim compte comme vide, et des avis différents (même marque, jour, produit, pays, source et
   note) sont donc pris pour des jumeaux. **Aucune donnée n'est perdue ni mal enregistrée** : la clé d'unicité
   (`raw_hash`) porte sur la mention complète. Correction à faire : `verbatim_field = "content trad"` par défaut, et
   valeurs par défaut écrites dans la configuration figée (traçabilité).
3. **Fin de pagination** : page vide avec le même curseur, conforme à la règle retenue, sans avertissement.
4. **1 doublon** : deux mentions identiques sur tous les champs sauf `id`, dans la même page. Il est impossible de dire
   si c'est une répétition de l'API ou deux avis réellement distincts. C'est la limite assumée de
   `decision_identifiant.md`. Conséquence : 3 164 uniques pour 3 165 annoncées. À trancher pour la validation
   (sprint 6).
5. Aucun `id` API porté par deux mentions différentes dans cet export : pas d'alerte.
6. Mesures pour 500 000 mentions : ≈ 500 pages × 3,5 à 4 s ≈ **30 à 35 min** ; ≈ **0,5 à 0,6 Go** de JSON brut
   pendant la collecte (hors index et compression Postgres).

---

## Sprint 6 — Validation, fichiers finaux, téléchargements, rétention (15/10/2026)

### Décisions de l'utilisateur prises avant le sprint
- **Règle A** pour la complétude : COMPLETED si **toutes les mentions annoncées ont été reçues** et si chaque écart entre
  « uniques » et « annoncées » est **expliqué et tracé** (doublons listés dans le manifeste avec leurs deux `id`), sans
  aucune mention rejetée. Cas d'origine : le doublon du premier export réel, le même avis « Syndicated reviews France »
  au mot près, à la même seconde, sous deux `id` (136236603 et 136556622). C'est très probablement un avis syndiqué
  deux fois chez le fournisseur.
- **Jumelles signalées, non bloquantes** (écart avec la spec) : les deux avis sont gardés, rien n'est fusionné.
- **CSV analytique** (`postprocess_reviews`) reporté au sprint 7.

### Fait
| Fichier | Rôle |
|---|---|
| `bulk_export/fingerprints.py`, `models.py` | Champ verbatim `content trad` par défaut (constaté sur l'API réelle) ; réglages par défaut **écrits** dans la configuration figée |
| `bulk_export/storage.py` | Supabase Storage par l'API HTTP : envoi par morceaux de 6 Mo **reprenable** (TUS), lecture en flux, suppression, lien signé ; `LocalStorage` pour les tests |
| `bulk_export/downloads.py` | Fabrication **en flux** : lots `.jsonl.gz` (référence brute), CSV complet, manifeste, ZIP, CSV « DONNÉES PARTIELLES » |
| `bulk_export/validation.py` | Les contrôles (tableau ci-dessous), tout en flux |
| `bulk_export/finalize.py` | VALIDATING → fichiers → contrôles → statut ; effacement des mentions après COMPLETED ; rétention ; suppression |
| `bulk_export/runner.py` | Validation **enchaînée automatiquement** après la collecte, sous bail ; « Valider » pour la relancer |
| `bulk_export/migrations/003_files.sql` | Empreinte du contenu des fichiers ; dates d'effacement et d'expiration (**à exécuter dans Supabase**) |
| `module4_bulk_export_v2.py` | Monitor (résultats de validation, bouton Valider), **Downloads** (liens signés), **History** (filtres, Reprendre, Valider, fichier partiel, Supprimer avec confirmation) |
| `tests/` | +28 tests : stockage (8), fichiers (5), validation de bout en bout (14), page (1) |

### Les contrôles
| Contrôle | Comment | Si échec |
|---|---|---|
| Pagination terminée | `pagination_finished` | INCOMPLETE |
| Complétude (règle A) | reçues = annoncées, et uniques + doublons tracés + rejetées = annoncées | INCOMPLETE |
| Aucune mention rejetée | `error_count` = 0 | INCOMPLETE |
| Données stables | `/metrics` redemandé à la fin = chiffre du début | INCOMPLETE |
| Doublons tracés | autant de doublons listés que comptés | FAILED |
| Intégrité des lots | chaque lot **relu depuis Storage** : empreinte du fichier, empreinte du contenu, nombre de lignes | FAILED |
| Conservation et unicité | chaque ligne relue = la mention en base **au caractère près**, dans le même ordre, même empreinte. La base interdit deux fois la même empreinte, donc il n'y a pas de doublon dans les lots. | FAILED |
| Cohérence | lignes relues = uniques = lignes enregistrées ; CSV : lignes = uniques | FAILED |
| CSV | empreinte relue dans Storage + chaque cellule comparée à la mention en base | FAILED |
| Jumelles | comptées et signalées | non bloquant |
| Manifeste et ZIP | relus après envoi, empreinte identique | FAILED |

### Choix techniques
- **Lots** : `batch_0001.jsonl.gz`… (25 000 mentions par défaut). Chaque ligne = le texte JSON reçu, tel quel.
- **CSV** : UTF-8 avec BOM (Excel), séparateur virgule, une colonne par champ dans l'ordre d'apparition, textes
  inchangés, listes et nombres en texte JSON, `null` en cellule vide. Ces règles sont écrites dans le manifeste.
- **ZIP** : lots décompressés (`.jsonl`), manifeste, CSV.
- **Après COMPLETED**, les mentions sont effacées de la base (les fichiers validés font référence). La taille
  moyenne d'une mention est gardée pour les estimations. Rien n'est effacé si la validation échoue.
- **Rétention** : à l'ouverture de la page, les fichiers des exports COMPLETED de plus de `retention_days` sont
  supprimés de Storage. La fiche reste dans l'historique, marquée « fichiers expirés ».
- **Suppression** : impossible pendant qu'un export tourne. Double confirmation pour un export encore reprenable.
- **Fichier partiel** (export non validé) : nom `DONNEES_PARTIELLES_…csv`, et première ligne « DONNÉES PARTIELLES ».
- Les tests ont vérifié qu'un lot modifié d'un seul caractère, ou contenant une ligne dupliquée, donne bien FAILED.
  Contre-épreuve : en désactivant les contrôles, ces deux tests échouent.

### Tests
- `pytest` : **259 réussis** avec la base de test.
- **Non testé ici : le vrai Supabase Storage** (le faux serveur reproduit le protocole documenté). À vérifier par
  vous : premier export validé, téléchargement par lien signé d'un gros fichier sans ralentir l'application.

### Points ouverts
1. **À faire par vous** : bucket privé `bulk-exports`, limite de taille à 1 Go, clé secrète et `supabase_url` dans les
   secrets, `003_files.sql` (LISEZMOI §1.3 et §1.6).
2. L'export de test du 15/10 (« Avene - FR - 26 ») a une configuration d'avant la correction : il ne pourra pas être
   validé. Supprimez-le depuis History et relancez-le.
3. Vérifications manuelles du sprint 5 (3 à 5) toujours à faire, idéalement sur un export plus gros.
4. Sprint 7 : CSV analytique, recette 500 000 mentions, optimisation.

### Premier essai de validation sur Supabase (15/10/2026) — « AV_FR_26 », `exp_20261015T151721Z_d9c8e0f6`
- Collecte identique au premier essai (3 165 reçues, 3 164 uniques, 1 doublon). **Jumelles : 2** au lieu de 970 : la
  correction du champ verbatim fonctionne, et ce sont de vrais avis jumeaux.
- **Validation FAILED** à l'envoi du premier lot : `HTTP 400 — 403 AccessDenied — Invalid Compact JWS`. Cause :
  la clé utilisée est une nouvelle clé `sb_secret_…`, que l'envoi par morceaux de Supabase Storage n'accepte pas
  (il attend un jeton JWT). **Correction** : utiliser la clé `service_role` de l'onglet « Legacy API Keys »
  (LISEZMOI §1.6 mis à jour). Le message d'erreur l'indique maintenant directement.
- Aucune donnée perdue : les mentions sont restées en base. Après le changement de clé, il suffit de cliquer sur
  **Valider**.
- ✅ **Après le passage à la clé `service_role` : validation réussie, export COMPLETED** (confirmé par l'utilisateur
  le 15/10/2026). Premier export de bout en bout sur l'infrastructure réelle : collecte → fichiers dans Storage →
  relecture et contrôles → COMPLETED (règle A, 1 doublon tracé, 2 jumelles signalées).

---

## Accès par mot de passe (15/10/2026) — spec « Accès par mot de passe (Streamlit) »

### Fait
| Fichier | Rôle |
|---|---|
| `auth.py` (nouveau) | Implémentation de référence de la spec : écran « Accès protégé », `hmac.compare_digest` (S2), saisie effacée de la session (S4), blocage 5 min après 5 échecs (S5), « Se déconnecter » dans la barre latérale (F4) |
| `main_app.py` | `exiger_mot_de_passe()` juste après `st.set_page_config`. **Les modules ne sont importés qu'ensuite** : avant, l'import d'`api_client` créait le client API dès la première ligne. Aucun autre changement. |
| `module4_bulk_export_v2.py` | Même protection s'il est lancé directement |
| `tests/test_auth.py` | 11 tests ; tests des pages adaptés (connexion préalable) |

### Renforcements par rapport au code de référence (validés)
- **Secret vide refusé** (S6) : avec `APP_PASSWORD = ""`, le code de référence laissait entrer une saisie vide.
- **Secret de moins de 16 caractères refusé** (S7) : l'application ne s'ouvre pas (« Configuration invalide »).
- Le mot de passe est enregistré comme secret à masquer dans tous les messages et journaux.
- Le contrôle du secret s'applique aussi à une session déjà connectée : si le secret est retiré, l'accès se ferme.

### Points d'attention
- **Pas de dossier `pages/`** dans ce dépôt : tout passe par `main_app.py`. Si une page y est ajoutée un jour, elle
  doit commencer par `st.set_page_config(...)` puis `exiger_mot_de_passe()`.
- Les modules 1 à 3 gardent leur lancement direct (`streamlit run module3_bulk_export.py`) **sans** mot de passe :
  la règle n°1 interdit de modifier le module 3. Ce mode n'est pas utilisé sur Streamlit Cloud, dont le fichier
  principal est `main_app.py`.
- Un export lancé **continue en arrière-plan** après une déconnexion, comme après la fermeture de l'onglet.
- Limites de la spec (mot de passe partagé, blocage par session, pas de « se souvenir de moi ») : inchangées.

### Tests automatiques (outil de test de Streamlit)
| Réf. | Résultat |
|---|---|
| T1 / S3 | ✅ Seul l'écran de mot de passe s'affiche, **aucun appel réseau ni connexion à la base**, **aucun module de l'application chargé** (contre-épreuve : si le contrôle est placé après le chargement, le test échoue) |
| T2 / F3 | ✅ « Mot de passe incorrect. », rien d'autre |
| T3 / F2 | ✅ Application complète (5 entrées du menu) |
| T4 / S5 | ✅ Blocage après 5 échecs, qui persiste dans la session |
| T5 / F5 | ✅ Nouvelle session : mot de passe redemandé |
| T6 / F4 | ✅ « Se déconnecter » ramène à l'écran de mot de passe |
| T9 / S6, S7 | ✅ Secret absent ou vide : « Configuration manquante » ; secret trop court : « Configuration invalide » |
| S2, S4 | ✅ `hmac.compare_digest` ; saisie absente de la session après vérification |

`pytest` : **271 réussis** avec la base de test.

### À vérifier par vous sur l'application déployée
- [ ] T1 à T6 et T9 à la main.
- [ ] T7 : sans objet (aucune sous-page).
- [ ] T8 : commande dans LISEZMOI §0.

---

## Correctif du 19/10/2026 — plantage des modules 2 et 3 (« legacy ») avec pandas 3

- **Symptôme** (Streamlit Cloud, Python 3.14) : `AttributeError` dans `module3_bulk_export.py` ligne 597, à l'affichage
  des résultats : `DataFrame.applymap` n'existe plus dans pandas 3. Le module 2 a le même problème (lignes 412 et 441).
- **Cause** : risque relevé dès l'audit du sprint 0 (`audit_code.md`, point 8). `requirements.txt` demandait seulement
  `pandas>=2.0.0`, et Streamlit Cloud a installé pandas 3 lors d'un redéploiement.
- **Correction** : `pandas>=2.0.0,<3` dans `requirements.txt`. Les modules 2 et 3 ne sont **pas** modifiés (règle n°1).
  pandas 2.3.3 existe pour Python 3.14 (vérifié).
- **Test ajouté** : `tests/test_legacy_pandas.py` fait afficher des résultats par les modules 2 et 3. Il échouait avec
  pandas 3.0.5 (bug reproduit) et passe avec pandas 2.3.3. `pytest` : **273 réussis**.
- Point ouvert : pandas avertit que `applymap` est obsolète. Pour passer un jour à pandas 3, il faudra remplacer
  `applymap` par `map` dans les modules 2 et 3, avec l'accord explicite de l'utilisateur pour le module 3.

---

## Formats Excel et « plat » (19/10/2026)

### Fait
| Fichier | Rôle |
|---|---|
| `bulk_export/derived.py` (nouveau) | Excel en flux (openpyxl, écriture seule) ; fichier plat par paquets de 5 000 avec `utils.postprocess_reviews` **réutilisée telle quelle** |
| `bulk_export/downloads.py` | Fabrication et envoi des deux fichiers pendant la validation (`export_complete.xlsx`, `export_plat.csv`) |
| `bulk_export/validation.py` | Intégrité (empreinte relue dans Storage) et cohérence (lignes = uniques) des deux fichiers |
| `bulk_export/models.py` | Deux nouveaux formats, `xlsx` et `plat`, **cochés par défaut** |
| `bulk_export/finalize.py` | Notes sur les formats dérivés dans la validation et le manifeste (`derived_formats`) |
| `module4_bulk_export_v2.py` | Cases à cocher dans New Export, liens dans Downloads |
| `tests/` | +13 tests (`test_derived.py`, validation de bout en bout, altération des fichiers) |

### Décisions (validées)
- **Excel** = mêmes colonnes et mêmes valeurs que le CSV complet (listes en texte JSON, nombres en nombres). Dans
  l'Excel **seulement** : une cellule de plus de 32 767 caractères est coupée, et les caractères de contrôle
  interdits sont retirés. Les deux sont comptés dans le manifeste. Un texte qui commence par « = » reste du texte
  (jamais une formule). Au-delà de 1 048 575 mentions, l'Excel n'est pas produit, et la raison est notée.
- **Fichier plat** = **identique au caractère près** au format plat existant (modules 2 et 3), y compris `Sampling` avec
  une majuscule et la date au 1er du mois. Traité par paquets avec les colonnes et les types du fichier entier (ex. une
  note entière devient 5.0 partout dès qu'une note manque, comme avec pandas). Tests : identique pour des paquets de
  1, 2, 3 et 1 000 mentions. Séparateur `;`, UTF-8 avec BOM.
- Ni l'un ni l'autre n'est ajouté au ZIP. Les lots JSONL restent la référence brute ; Excel et plat sont des formats
  dérivés (règle n°3).
- Les exports validés **avant** ce changement n'ont pas ces fichiers. Il faut les relancer.
- `utils.py` et les modules 1 à 3 ne sont pas modifiés.

### Mesures (20 000 fausses mentions, machine de développement)
Fichier plat : 2,3 s · Excel : 2,8 s (≈ 1 Mo). Pour 500 000 mentions, compter 1 à 2 min chacun ici, et
probablement 2 à 4 min sur Streamlit Cloud (à mesurer au sprint 7).

`pytest` : **284 réussis**.

---

## Lot 1A — Conservation du brut (21/10/2026)

Sprint : `docs/chantier/SPRINT_L1A_conservation_du_brut.md`. Décision : `decision_conservation_brut.md` (nouveau).

### Fait
| Fichier | Rôle |
|---|---|
| `bulk_export/settings.py` | `purge_raw_after_validation` (faux par défaut, `BULK_EXPORT_PURGE_RAW`) ; `retention_days` : défaut **0** = jamais, négatif refusé ; `alerte_taille_base_go` (défaut 6, `BULK_EXPORT_ALERTE_TAILLE_BASE_GO`) |
| `bulk_export/finalize.py`, `runner.py` | La purge après COMPLETED n'a lieu que si le réglage est vrai ; sinon événement « Mentions conservées en base (purge désactivée) ». `apply_retention()` ne fait rien si `retention_days` vaut 0 |
| `bulk_export/state_store.py` | `exports_with_expired_files(0)` → aucun export (deuxième protection) ; `database_sizes()` (taille de la base et de `raw_mentions`) |
| `bulk_export/migrations/004_conservation.sql` (nouveau) | Index `raw_mentions_compass_id_idx` sur `raw_mentions (compass_id)`, rejouable, schéma `bulk_export` seulement |
| `bulk_export/rehydrate.py` (nouveau) | Réhydratation depuis les lots : `python -m bulk_export.rehydrate exp_…` et `--list` |
| `bulk_export/ui_logic.py`, `module4_bulk_export_v2.py` | Export History : tailles en haut et avertissement au-delà du seuil, colonne « Brut en base » (conservé / effacé le …), bouton **« Réhydrater le brut »** (P2, demandé par l'utilisateur) |
| `tests/` | +21 tests : `test_conservation_db.py` (nouveau), réglages, colonne et seuil, affichage d'Export History |
| Docs | `ADAPTATION_SUPABASE.md` (ligne Rétention, secrets), `LISEZMOI.md` (script 004, secrets), `EXECUTION.md` (commandes) |

### Décisions
- `page_no = 0` pour les lignes réhydratées (les lots ne gardent pas la page ; une vraie page commence à 1).
- Les empreintes sont **recalculées** avec les réglages de l'export, pas recopiées. Le test le vérifie : mêmes
  `seq`, `mention_id`, `raw_json`, `content_key`, `compass_id` et `api_id` qu'avant la purge, et les doublons tracés
  retrouvent l'`id` API de la copie gardée.
- La taille affichée est celle de **toute** la base (Compass compris) : c'est elle que Supabase limite à 8 Go.
  1 Go = 1 024³ octets (même unité que le reste de la page).
- Le bouton « Réhydrater » travaille pendant l'affichage de la page (sablier). Pour un gros export, il peut prendre
  plusieurs minutes : la ligne de commande reste possible.
- Le test d'origine « purge après COMPLETED » est gardé, avec la purge activée explicitement (comportement inchangé).

### À faire par l'utilisateur
1. Exécuter `bulk_export/migrations/004_conservation.sql` dans le SQL Editor de Supabase (après 001 à 003).
2. Secrets `[bulk_export]` : `retention_days = 0` (remplace 3650) **une fois cette version déployée** — pas avant :
   l'ancienne version supprimerait tous les fichiers avec 0. Laisser `purge_raw_after_validation` absent.
3. Réhydrater les exports déjà purgés : Export History → choisir l'export → « Réhydrater le brut »
   (ou `python -m bulk_export.rehydrate --list` puis `python -m bulk_export.rehydrate exp_…`).

### Exports réhydratés
Pas d'accès à la base réelle depuis l'environnement de développement : liste à compléter après le passage de
l'utilisateur (`export_id`, nombre de mentions, date).

| Export | Mentions | Réhydraté le |
|---|---|---|
| *(à compléter)* | | |

### Points ouverts
- Mesurer la taille réelle du brut d'un export de 500 000 mentions (estimation de la spec : ≈ 1 Go).
- Archivage du brut ancien hors de la base : à décider quand l'avertissement de taille se déclenchera.

`pytest` : **305 réussis** (284 + 21), base Postgres 16 locale comprise.

### Premier essai de réhydratation (21/10/2026) — `exp_20261020T090611Z_eaca94e3`
- **Refus** à la lecture du premier lot : `HTTP 400 — headers must have required property 'authorization'`.
  Cause : la clé Storage utilisée ne commence pas par `eyJ`, donc le programme ne l'envoie pas comme jeton
  (en-tête `Authorization`), et Storage refuse la lecture. Rien n'a été écrit en base (tout ou rien).
- Correctifs : les espaces ou retours à la ligne copiés autour de `supabase_service_key` sont retirés ; ce refus
  affiche maintenant un message qui explique quoi faire (clé `service_role` de « Legacy API Keys », qui commence par `eyJ…`).
- `pytest` : **307 réussis**.

## Sprint charte — Consumer Voice (22/10/2026)

Référence : `docs/charte/DESIGN_GUIDE.md` et `docs/charte/SPRINT_charte.md`. Seule l'apparence change.

### Fait
- Kit installé tel quel (v1.0.0, identique à `rddt_connector` et `mvp_verbatim_import`) : `.streamlit/config.toml`,
  `charte/`, `charte_demo.py`, `tests/test_charte.py` ; guide, aperçus et sprint dans `docs/charte/`.
  `requirements.txt` : `streamlit>=1.66` (`pandas<3` gardé).
- `main_app.py` : titre « Collecte Semantiweb », icône Material, `appliquer_charte()` juste après le mot de passe,
  `bandeau()` à la place du titre, menu sans emoji avec icônes Material. Le routage ne dépend plus du texte des
  libellés (constantes).
- Nouvelle entrée **Accueil** (décision de l'utilisateur) : le guide des modules et le parcours recommandé
  n'étaient jamais affichés (le menu choisissait toujours un module). Contenu mis à jour avec Bulk Export V2.
- Modules 1 et 2 : plus de `st.title`, contenu rangé en `section()`, emojis remplacés par des icônes Material,
  chiffres clés en `st.metric(border=True)` au format français, messages d'erreur « ce qui s'est passé + quoi
  faire ». Les choix qui comparaient un libellé avec emoji (`"🚀 Export en masse" in …`, `startswith("🔍")`)
  comparent maintenant une constante : même comportement.
- Module 2 : les lignes de diagnostic de la pagination (« Debug ») sont repliées dans « Détails techniques de la
  pagination » au lieu de s'afficher au milieu de l'écran.
- `utils.py` (partagé avec le module 3, décision de l'utilisateur) : emojis retirés des messages, des boutons de
  téléchargement et du journal des exports ; nouveau `format_nombre()` (189 824).
- Bulk Export V2 : onglets en français (« Nouvel export », « Suivi », « Téléchargements », « Historique »,
  décision de l'utilisateur) dans un `st.segmented_control` ; étapes Configurer → Estimer → Lancer ; statuts en
  badge (`badge_statut`) et en français dans les listes (`libelle_statut`) ; une seule action principale visible
  (Arrêter, Valider ou Reprendre) ; limite de la version 1 dans un encadré « à retenir » ; « Brut en base
  (raw_mentions) » devient « Mentions brutes conservées en base ».
- Le module 3 (`module3_bulk_export.py`) n'est **pas modifié** : il garde son titre et ses emojis ; le thème
  s'y applique seul. Il n'a pas de bandeau, pour éviter un double titre.
- Captures avant / après (clair, sombre, 420 px) : `docs/charte/captures_api_explorer/` (fausses données `fake`,
  police de remplacement faute d'accès à Google Fonts).

### Corrigés à la suite du sprint (demande de l'utilisateur, commits séparés)
- **Sécurité (règle n°8)** — `api_client.py` : en cas d'erreur HTTP ou de coupure réseau, l'écran affichait
  l'adresse de l'appel **token compris**, et la réponse brute. Les messages passent maintenant par `mask()` ; le
  token est enregistré comme secret à la création du client et n'est plus ajouté au dictionnaire de l'appelant.
  Test : `tests/test_api_client_secrets.py` (fuite reproduite sur l'ancien code).
- `utils.clean_old_exports` : le bloc copié de `log_export_activity` est supprimé ; « Nettoyer le journal »
  n'affiche plus le faux avertissement « Export non enregistré dans le journal ». Test :
  `tests/test_journal_exports.py`.

### Point ouvert
- Le module 3 garde ses emojis tant que sa modification n'est pas autorisée.

`pytest` : **320 réussis** (307 + 11 tests de la charte + 2 tests des corrections), base Postgres 16 locale comprise.

### Noms des pages (22/10/2026, décision de l'utilisateur)
Noms affichés alignés sur l'usage de chaque page :
- module 3 (« Export bulk », V1) → **Export par segment** : catégories, segments, marques ;
- module 4 (« Bulk Export V2 ») → **Synchro mensuelle du marché**.
Seuls les libellés à l'écran changent : les fichiers, le paquet `bulk_export`, le schéma `bulk_export` et la
documentation gardent le nom « Bulk Export V2 ». Le module 3 étant non modifiable, son propre titre
(« Module 3 - Export Bulk ») ne change pas.
