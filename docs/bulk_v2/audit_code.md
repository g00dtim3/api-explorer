# Audit du code existant — Sprint 0

> Lecture seule du code au commit `452e17f` (14/10/2026). Aucun fichier applicatif n'a été modifié.
> Les numéros de ligne renvoient à ce commit.
> Légende des niveaux : 🔴 bloquant pour Bulk Export V2 · 🟠 à traiter · 🟢 réutilisable tel quel.

## Résumé en 8 points

1. 🔴 **Le token peut s'afficher à l'écran.** Il est placé dans l'adresse de chaque appel (`?token=…`). En cas d'erreur HTTP, l'adresse complète est affichée à l'utilisateur (`api_client.py:42`). En cas de coupure réseau, le message d'erreur de `requests` contient lui aussi l'adresse (`api_client.py:47`).
2. 🔴 **Pas de timeout.** `requests.get(url, …)` n'a pas de délai maximal (`api_client.py:39`) : un appel qui ne répond pas bloque indéfiniment.
3. 🔴 **Une erreur ressemble à une réponse vide.** Toute erreur (401, 429, 500, coupure réseau, JSON invalide) renvoie `{}`. Le code appelant ne peut savoir ni le code HTTP, ni s'il faut réessayer, ni lire `Retry-After`.
4. 🔴 **Les réponses sont mises en cache 1 heure**, erreurs comprises (`@st.cache_data(ttl=3600)`, `api_client.py:19`). Pour un gros export, cela veut dire : toutes les pages restent en mémoire pendant 1 h, une erreur reste « collée » pendant 1 h, et relancer le même export dans l'heure relit le cache au lieu de l'API.
5. 🟠 **La boucle du module 3 garde tout en mémoire** (`all_docs`) et reconstruit l'ensemble des IDs à chaque page : de plus en plus lent à mesure que l'export grossit.
6. 🟠 **La limite de 1 000 pages arrête la boucle sans aucun message.** Avec 500 mentions par page (valeur par défaut), un export s'arrête donc en silence à 500 000 mentions.
7. 🟠 **`postprocess_reviews()` modifie fortement les données** : renommages, date ramenée au 1er du mois, verbatim d'origine supprimé… (liste complète au §5). Cette fonction est donc réservée au format analytique dérivé.
8. 🟠 **Incompatibilité avec pandas 3.** `df.applymap(...)` est utilisé dans les modules 2 et 3, mais pandas 3.0 a supprimé cette fonction. `requirements.txt` demande seulement `pandas>=2.0.0`, donc une nouvelle installation peut prendre pandas 3 et faire planter l'affichage des résultats. Constaté sur cette machine (pandas 3.0.5 : `applymap` absent). Je ne sais pas quelle version Streamlit Cloud installe aujourd'hui (**à vérifier**).

---

## 1. `api_client.py` — le client API

### Méthodes disponibles
| Méthode | Appel API | Remarque |
|---|---|---|
| `get_quotas()` | `/quotas` | Champs lus ailleurs : `used volume`, `remaining volume`, `quota`, `end date` |
| `get_categories()`, `get_countries()`, `get_markets()`, `get_ratings()` | listes de référence | sans paramètre |
| `get_brands()`, `get_sources()`, `get_attributes()`, `get_products()` | listes filtrées | |
| `get_metrics(**params)` | `/metrics` | Le volume se lit dans `nbDocs` (`module3_bulk_export.py:134`) |
| `get_reviews(**params)` | `/reviews` | Renvoie le bloc `result` ; les mentions sont dans `docs`, le curseur suivant dans `nextCursorMark` |

Tous les appels passent par `fetch()` → `_fetch_cached()`.

### Où est lu le token
`self.TOKEN = st.secrets["api"]["token"]` (`api_client.py:13`), c'est-à-dire dans `.streamlit/secrets.toml`, section `[api]`.
Conséquence : le client **ne fonctionne qu'à l'intérieur de Streamlit**. Un moteur lancé en ligne de commande (prévu dans `ADAPTATION_SUPABASE.md`) devra pouvoir lire le token autrement, par exemple dans une variable d'environnement.

### Comment l'appel est construit
- Le token est ajouté **dans l'adresse** : `params["token"] = TOKEN` (`api_client.py:30`), pas dans un en-tête HTTP.
- Chaque paramètre est encodé strictement (`urllib.parse.quote` avec `safe=''`).
- Un objet `APIClient` unique est créé à l'import du module (`api_client.py:150`).

### Gestion des erreurs : ce qui manque
| Point | Constat | Ligne |
|---|---|---|
| Timeout de connexion / de lecture | **absent** | 39 |
| Nouvelles tentatives, backoff, `Retry-After` | **absents** | — |
| Code HTTP transmis à l'appelant | **non** : tout code ≠ 200 donne `{}` | 41–45 |
| Distinguer « erreur » de « réponse vide » | **impossible** | 41–48 |
| Token masqué dans les messages | **non** : l'adresse complète est affichée | 42, 47 |
| En-têtes de réponse (quota, `Retry-After`) | **ignorés** | — |
| Réponse 200 sans clé `result` | renvoie `{}` en silence | 41 |

### Nettoyage des paramètres dans `get_metrics` / `get_reviews`
Une valeur est **retirée sans prévenir** si elle vaut `"ALL"` ou si elle est « vide » au sens Python (`None`, `""`, `0`, `[]`). Les listes sont jointes par des virgules. `get_metrics` et `get_reviews` appliquent exactement la même règle : 🟢 cohérent.

### Le cache (point important)
`@st.cache_data(ttl=3600)` garde chaque réponse 1 heure, rangée selon `(endpoint, params)` :
- un échec (`{}`) est lui aussi gardé : **relancer immédiatement le même appel redonne l'échec sans interroger l'API** ;
- chaque page de `/reviews` reste en mémoire 1 h : pour 500 000 mentions, cela revient à garder l'intégralité en RAM, ce qui contredit la règle n°2 ;
- deux parcours dans la même heure : le second lit le cache. Un test de stabilité de l'ordre ou une reprise ne verrait donc pas l'API réelle.

➡️ **Pour V2** : un chemin d'appel `/reviews` **sans cache**, avec timeouts et erreurs structurées (code HTTP, `Retry-After`, adresse masquée). Il faut l'ajouter à côté de l'existant, sans changer le comportement de `fetch()` pour les modules 1 à 3 (règle de rétrocompatibilité).

---

## 2. `module3_bulk_export.py` — la boucle d'export actuelle

Fonction `execute_bulk_export()` (lignes 342–516). Déroulé :

1. Paramètres = `build_filter_params(filters)`, plus `rows` (10 à 1 000, **500 par défaut**) et éventuellement `random` (si la case « Randomiser » est cochée).
2. Volume attendu = `/metrics` → `nbDocs`, **avec les mêmes filtres** (`build_filter_params(filters)`, sans `rows` ni `random`).
3. Curseur de départ `"*"`, envoyé dans le paramètre **`nextCursorMark`** (le commentaire ligne 404 indique que `cursorMark` ne fonctionnait pas).
4. Boucle `while page_count < 1000` (10 en aperçu).

### Conditions d'arrêt (dans l'ordre du code)
| # | Condition | Ce qui est affiché | Problème pour V2 |
|---|---|---|---|
| 1 | Réponse `{}` (n'importe quelle erreur) | « Erreur API » | Erreur non distinguée, pas de nouvelle tentative |
| 2 | `docs` vide ou absent | « Pas de données » | Fin normale ou anomalie ? Indéterminé |
| 3 | Aperçu et ≥ 100 mentions | info | — |
| 4 | `nextCursorMark` absent | « Fin : pas de nextCursorMark » | Fin normale ou anomalie ? Indéterminé |
| 5 | `nextCursorMark` == curseur envoyé | « Fin : cursor identique » | Règle de fin Solr classique, **à confirmer** pour cette API |
| 6 | Nombre récupéré ≥ `nbDocs` | « Toutes les reviews récupérées » | Arrêt sur le chiffre de `/metrics` : si ce chiffre est faux ou change, l'arrêt se fait au mauvais moment |
| 7 | 1 000 pages atteintes | **rien** | Arrêt silencieux |

Toutes ces fins débouchent sur le même message « ✅ terminé ». Si le nombre récupéré est inférieur au volume attendu, un simple avertissement s'affiche (« peut être dû aux limites de pagination en environnement DEV »).

### Déduplication actuelle (lignes 424–437)
- Elle n'est active que si la **première** mention de la page possède un champ `id`.
- À chaque page, **tous les IDs déjà reçus sont relus** (`{doc.get('id') for doc in all_docs}`) : le coût grandit avec le volume.
- Une mention sans `id` est **gardée** sans signalement.
- Les doublons **à l'intérieur d'une même page** ne sont pas détectés.
- Un doublon au contenu différent est jeté en silence : il n'y a aucune comparaison.
- Le champ identifiant utilisé par le code est **`id`**.

### Autres points
- `random` est proposé à l'utilisateur pour le mode complet : à interdire en V2 (règle n°11).
- Une pause de 0,1 s est faite toutes les 5 pages : ce n'est pas une vraie gestion du débit.
- Les résultats sont rangés dans `st.session_state.all_docs` et sont donc perdus si la page se recharge.
- `log_export_activity()` écrit `review_exports_log.csv` sur le disque local, effacé sur Streamlit Cloud. Le token n'y figure pas (🟢).
- Beaucoup d'affichages de debug (`st.write`) montrent les curseurs : sans danger pour le token, mais bruyant.

---

## 3. `build_filter_params()` (`utils.py:46`)

Paramètres produits :

| Filtre (session) | Paramètre API | Règle |
|---|---|---|
| `start_date` / `end_date` | `start-date` / `end-date` | tel quel |
| `category`, `subcategory` | `category`, `subcategory` | ignoré si `"ALL"` |
| `brand` (liste) | `brand` | joint par des virgules |
| `country`, `source`, `market` (listes) | idem | ignoré si la liste **contient** `"ALL"` |
| `attributes`, `attributes_positive`, `attributes_negative` | `attribute`, `attribute-positive`, `attribute-negative` | joints par des virgules |
| liste de produits (option, module 2 uniquement) | `product` | lue dans `st.session_state` |

**Mêmes paramètres pour `/reviews` et `/metrics` ?** Oui dans le module 3 : les deux partent du même `build_filter_params(filters)`. `/reviews` reçoit en plus `rows`, `nextCursorMark` et éventuellement `random`, ce qui est normal. 🟢 Réutilisable.
Attention : la fonction lit `st.session_state` (option produits). Pour un moteur hors Streamlit, il faudra lui passer les filtres figés plutôt que l'état de la session.

---

## 4. `display_download_buttons()` (`utils.py:417`) et téléchargements du module 3

- Tout est construit **en mémoire** : `pd.json_normalize(all_docs)` crée un DataFrame de **toutes** les mentions (`module3_bulk_export.py:625`). Ensuite, les listes et dictionnaires sont convertis en texte avec `str()`.
- Pour chaque bouton, le fichier entier est généré en mémoire : CSV (`to_csv`), Excel (`openpyxl`), puis format plat (`postprocess_reviews` sur une **copie** du DataFrame). On a donc plusieurs copies complètes en RAM, recalculées à **chaque** interaction Streamlit.
- CSV : séparateur `,`, encodage `utf-8-sig` (avec BOM, pour Excel). Format plat : séparateur `;`, `utf-8-sig`.
- Ce n'est pas utilisable pour 500 000 mentions. **À remplacer** en V2 par des fichiers déjà générés et un lien signé (`ADAPTATION_SUPABASE.md` §2).

### Transformations faites **même sur le CSV « normal »** (pas seulement le format plat)
| Transformation | Effet |
|---|---|
| `json_normalize` | Un objet imbriqué `{"a": {"b": 1}}` devient une colonne `a.b` |
| `str()` sur les listes / dictionnaires | Écriture à la manière de Python (`['x', 'y']`, apostrophes) et non en JSON (`["x","y"]`) |
| Ordre des colonnes | Ordre d'apparition dans les données, donc pas forcément stable d'un export à l'autre |

➡️ Pour le CSV « référence » de V2, il faudra une règle explicite d'aplatissement qui ne perd rien (par exemple listes et objets écrits en JSON), et la documenter.

---

## 5. `postprocess_reviews()` (`utils.py:262`) — liste complète des transformations

Utilisée uniquement pour le bouton « Format plat ». Chaque étape, dans l'ordre :

| # | Transformation | Détail | Classement |
|---|---|---|---|
| 1 | Renommage `id` → `guid` | L'identifiant change de nom | Interdit sur données brutes · acceptable en analytique |
| 2 | Renommage `category` → `categories` | | Interdit brut · acceptable analytique |
| 3 | Renommage `content trad` → `verbatim_content` | Le verbatim **traduit** devient « le » verbatim | Interdit brut · acceptable analytique **si documenté** |
| 4 | Renommage `product` → `product_name_SEMANTIWEB` | | Interdit brut · acceptable analytique |
| 5 | Date convertie puis réécrite au format `01/MM/AAAA` | **Le jour est perdu** (tout passe au 1er du mois). Une date illisible devient vide (`errors='coerce'`). Le format d'entrée est deviné par pandas, avec un risque d'inversion jour/mois. | Interdit brut · acceptable analytique **avec réserve** : perte d'information à signaler |
| 6 | Ajout de `Sampling` (0/1) | 1 si `business indicator` contient « Sampling Rate » | Enrichissement · analytique uniquement |
| 7 | **Suppression de `content origin`** | Le verbatim **dans sa langue d'origine** disparaît | **Interdit brut** · acceptable analytique seulement si assumé |
| 8 | Ajout de 9 colonnes `attribute_Composition` … `attribute_Texture` | Valeur `positive` / `negative` / `neutre` / `0`, calculée à partir de `attributes`, `attributes positive`, `attributes negative` | Enrichissement · analytique uniquement |
| 9 | Règle « neutre » | Un attribut à la fois positif et négatif, ou cité sans polarité, devient `neutre` | Interprétation métier · analytique uniquement |
| 10 | Attributs hors liste ignorés | Seuls les 9 attributs prédéfinis sont gardés ; les autres disparaissent du résultat | Perte d'information · analytique uniquement |
| 11 | Lecture des attributs via `ast.literal_eval` | Ne marche que parce que les listes ont été converties en texte Python par `str()` juste avant ; sinon l'attribut est ignoré sans message | Fragile · à revoir en V2 |
| 12 | Ajout de la colonne `safety` | Synthèse de `Safety` + `Composition` (positive / negative / neutre / 0) | Enrichissement · analytique uniquement |
| 13 | **Suppression de `attributes`, `attributes positive`, `attributes negative`** | Les listes d'origine disparaissent | **Interdit brut** · acceptable analytique |
| 14 | Réordonnancement des colonnes | Colonnes d'origine, puis `attribute_*`, puis `safety` | Acceptable analytique |
| 15 | (au moment du téléchargement) séparateur `;` et encodage `utf-8-sig` | | Acceptable analytique |

**Conclusion :** `postprocess_reviews()` ne doit **jamais** toucher les JSONL ni le CSV de référence. En V2, on peut la réutiliser **uniquement** pour le format analytique dérivé (spec §6.2, « CSV plat », P1), et seulement après avoir corrigé deux points : la lecture des attributs (#11, qui dépend de la conversion `str()`) et la date (#5, perte du jour à afficher clairement).
Elle utilise aussi `iterrows()`, très lent sur de gros volumes. Elle devra donc tourner **lot par lot** et non sur 500 000 lignes d'un coup.

---

## 6. Dépendances et versions

| Élément | Valeur constatée |
|---|---|
| `requirements.txt` | `streamlit>=1.28.0`, `pandas>=2.0.0`, `requests>=2.31.0`, `urllib3>=2.0.0`, `openpyxl>=3.1.0` (aucune version figée) |
| Python (devcontainer) | 3.11 |
| Version de Streamlit réellement déployée | **inconnue** : aucune version figée, donc Streamlit Cloud installe la plus récente à chaque déploiement |
| pandas 3 | Supprime `DataFrame.applymap` utilisé par les modules 2 et 3 (voir résumé, point 8) |
| Bibliothèques absentes, nécessaires plus tard | client Postgres (ex. `psycopg`), client Supabase Storage, `pytest` |
| Tests existants | **aucun** dossier `tests/` |
| `.gitignore` | **absent** avant ce sprint : rien n'empêchait de commiter `secrets.toml` ou des exports. Ajouté au sprint 0. |

➡️ Recommandation pour le sprint 5 : figer au moins une borne haute (`pandas<3` ou remplacer `applymap` par `map` dans V2) et noter la version de Streamlit utilisée. **Je ne modifie pas `requirements.txt` dans ce sprint** (aucun changement applicatif).

---

## 7. Ce qu'on réutilise / remplace en V2

| Composant | Décision proposée |
|---|---|
| `APIClient` (listes de référence, `/metrics`, `/quotas`) | 🟢 Réutiliser |
| `APIClient.fetch` pour `/reviews` en masse | 🔴 Ne pas réutiliser tel quel (cache, pas de timeout, erreurs muettes, token dans les messages) → nouvel appel sans cache, ajouté à côté, rétrocompatible |
| Lecture du token | 🟠 Ajouter une alternative par variable d'environnement pour le mode ligne de commande |
| `build_filter_params()` | 🟢 Réutiliser, en lui passant des filtres figés |
| Boucle du module 3 | 🔴 Remplacer (moteur V2), sans toucher au module 3 |
| `postprocess_reviews()` | 🟠 Format analytique uniquement, lot par lot, après correction de #5 et #11 |
| `display_download_buttons()` | 🔴 Remplacer par des fichiers persistés + liens signés |
| `log_export_activity()` | 🟠 Remplacé par le journal et le manifeste persistés dans Postgres / Storage |
