# Audit de l'API Ratings & Reviews — Sprint 0

> **Source principale :** « Description de l'API Rating&Reviews pour Pierre Fabre v2.0 », mars 2025, 13 pages
> (fourni par l'utilisateur le 15/10/2026, non commité dans le dépôt).
> **Sources secondaires :** le code existant (`audit_code.md`).
>
> Statuts utilisés :
> - **documenté** : écrit dans la documentation du fournisseur (engagement écrit, mais pas encore vérifié en pratique) ;
> - **constaté** : observé dans le code existant ou lors d'un appel réel (petit volume, non garanti) ;
> - **confirmé par le fournisseur** : réponse explicite à nos questions (`questions_fournisseur.md`) ;
> - **indiqué par l'utilisateur** : information donnée par l'utilisateur, à partir de son usage réel de l'API ;
> - **inconnu** : ni documenté, ni observé. **Le moteur devra rendre ces points configurables** (règle n°10).
>
> Aucune valeur n'a été inventée. Le script `scripts/audit_api.py` n'a pas été écrit (décision du 14/10/2026).

## 1. Ce que dit la documentation

### Accès
- Domaine : `https://api-pf.ratingsandreviews-beauty.com/`
- Toutes les requêtes sont en **GET**. Le token est **obligatoire en paramètre d'adresse** (`?token=…`) ; aucun autre mode n'est documenté.
  ➡️ Le token figurera forcément dans chaque adresse appelée : le masquage dans les journaux et messages est **indispensable**.
- Réponses en JSON, avec `status` (exemples : `"success"`), `filters` (rappel des filtres reçus) et `result`.

### Endpoints utiles pour l'export
| Endpoint | Rôle | Consomme du quota ? |
|---|---|---|
| `GET /reviews` | Mentions détaillées (`result.docs`), plus `result.nbDocs` et `result.nextCursorMark` | **Oui** |
| `GET /metrics` | Nombre de mentions (`result.nbDocs`) | Non |
| `GET /quotas` | `quota`, `end date`, `used volume`, `remaining volume` | Non |

Endpoints de listes : `/attributes`, `/brands`, `/categories`, `/countries`, `/markets`, `/products` (`brand` obligatoire), `/ratings`, `/sources`, `/subcategories`.

### Paramètres de filtre
`attribute`, `attribute-negative`, `attribute-positive`, `brand`, `category`, `subcategory`, `country`, `market`, `product`, `rating`, `source`, `start-date`, `end-date`.
Paramètres techniques de `/reviews` : `rows`, `nextCursorMark`, `random`.
- Plusieurs valeurs : séparées par des virgules, avec une logique **OU** (`country=France,Italy`). Ce n'est pas possible pour `token`, `start-date`, `end-date`, `random`, `rows` et `nextCursorMark`.
- Valeurs **sensibles à la casse** (marques, pays, produits…).
- Le caractère `&` dans un nom de marque ou de produit doit être encodé en `%26`. 🟢 Le code actuel encode tous les caractères spéciaux, `&` compris.

### Champs d'une mention (liste officielle)
`id`, `attributes`, `attributes positive`, `attributes negative`, `brand`, `business indicator`, `category`, `country`,
`date`, `opinion`, `product`, `rating`, `source`, `subcategory`, `verbatim content`.

Dans l'exemple de la documentation :
- `id` est une **chaîne de chiffres** (`"97749480"`), pas un nombre ;
- `date` est au format ISO avec l'heure en UTC (`"2024-11-28T15:45:28Z"`) ;
- les attributs peuvent valoir `null` ;
- `rating` est un nombre (`5`) ;
- le verbatim contient des caractères Unicode échappés (`é`), qu'il faudra relire sans modification.

## 2. Tableau de l'audit

| # | Point | Valeur | Statut |
|---|---|---|---|
| 1 | Taille de page maximale `rows` | **1 000** (c'est aussi la valeur par défaut) | documenté |
| 2 | Champ identifiant natif | `id` (chaîne) est **présent mais pas fiable** : il est généré au moment de l'export, et les mêmes valeurs se retrouvent d'un export à l'autre | documenté (champ) · **indiqué par l'utilisateur** (15/10/2026) |
| 3 | Clé d'unicité retenue | Empreintes SHA-256 des champs source (`raw_hash` sans `id`, `content_key`, `compass_id`) | **validé** : `decision_identifiant.md` |
| 4 | Paramètre et format du curseur | Le curseur se passe dans `nextCursorMark` (curseur de départ `*`, selon le code) et revient dans `result.nextCursorMark`. Il fonctionne aussi en mode `random`. | documenté (paramètre et réponse) · constaté dans le code (`*`) |
| 5 | **Signal de fin de pagination** | Non décrit : curseur identique, page vide ou champ absent ? | **inconnu** |
| 6 | Ordre des résultats stable entre deux parcours ? | Non décrit (sans `random`) | **inconnu** |
| 7 | Durée de validité d'un curseur (reprise après plusieurs heures) | Non décrit | **inconnu** |
| 8 | Décompte du quota | Seul `/reviews` consomme du quota (documenté). **Le compte n'a plus de limite de quota** : exports illimités. | documenté · **indiqué par l'utilisateur** (15/10/2026) |
| 9 | Coût d'une page relue (nouvelle tentative, reprise) | Sans objet tant que le quota est illimité | — |
| 10 | Limites de débit, réponse 429, `Retry-After` | Non décrit | **inconnu** |
| 11 | Format des erreurs (codes HTTP, valeur de `status` ≠ `success`) | Non décrit | **inconnu** |
| 12 | `nbDocs` de `/metrics` = nombre réellement paginable par `/reviews` ? | Les deux renvoient `nbDocs` pour les mêmes filtres. L'égalité avec le nombre d'IDs récupérés n'est pas garantie. | documenté (champ) · égalité **inconnue** |
| 13 | Jeu de données stable pendant un export / snapshot | Non décrit | **inconnu** |
| 14 | Temps de réponse par page | Non décrit | **inconnu** (à mesurer pendant le sprint 1) |
| 15 | Taille moyenne d'une mention (brute et gzip) | L'exemple de la documentation n'est pas représentatif (verbatim de quelques mots) | **inconnu** (voir §4) |

## 3. Contradictions et écarts relevés

| # | Écart | Conséquence pour V2 |
|---|---|---|
| A | **Format de date des filtres** : le texte dit `YYYY-DD-MM`, mais tous les exemples utilisent `YYYY-MM-DD` (`2024-06-30` : le « 30 » ne peut pas être un mois). | Suivre les exemples (`YYYY-MM-DD`, ce que fait déjà l'application) et **poser la question**. Le format envoyé sera enregistré dans la configuration figée. |
| B | **Une ou plusieurs valeurs par filtre** : la page 2 dit « chaque filtre ne peut comprendre qu'une seule valeur », la page 3 décrit les valeurs multiples séparées par des virgules. | La page 3 est plus précise et c'est ce que fait l'application. À confirmer. Une valeur contenant elle-même une virgule serait ambiguë. |
| C | **Noms des champs du verbatim** : la documentation liste `verbatim content`, mais `postprocess_reviews()` attend `content trad` et `content origin`, qui ne figurent pas dans la documentation. | La documentation (mars 2025) est peut-être plus ancienne que le code (juillet 2025). **Le moteur V2 ne doit supposer aucune liste figée de champs** : il garde chaque mention telle quelle et seul `id` est obligatoire. La liste réelle sera relevée sur la première page d'un vrai export. |
| D | `market` est un filtre, mais n'apparaît pas dans les champs d'une mention. | Rien à faire pour les données brutes. À savoir pour l'analyse. |
| E | `/metrics` accepte aussi `random`, `rows` et `nextCursorMark` (sans effet documenté). | Le moteur appellera `/metrics` **uniquement avec les filtres**, comme le code actuel. |
| F | La documentation écrit une fois « newtCursorMark » (faute de frappe). | Aucune. |
| G | `rating` est un filtre documenté, mais `build_filter_params()` ne le gère pas. `/subcategories` existe, mais `APIClient` ne l'utilise pas. | Information pour le formulaire V2 (sprint 5). Pas un blocage. |

## 4. Volumétrie, durée et quota pour 500 000 mentions

### Ce qui est certain (calcul direct à partir de la documentation)
- **Nombre minimal d'appels `/reviews`** : 500 000 / 1 000 = **500 pages**.
- **Quota** : le compte n'a plus de limite (indiqué par l'utilisateur). Le contrôle « quota restant ≥ volume attendu » n'est **pas bloquant**. On garde l'affichage de `/quotas` à titre d'information, et un **avertissement** (pas un blocage) si l'API renvoie un jour un quota restant inférieur au volume attendu. Le moteur évite quand même de relire une page déjà sécurisée (économie de temps).

### Ce qui reste à mesurer
Taille réelle d'une mention et temps de réponse : **inconnus**. Formules à appliquer dès qu'une première page réelle aura été lue (sprint 1, mesure automatique dans le journal d'export) :

| Élément | Formule |
|---|---|
| Espace Postgres pendant la collecte | taille moyenne JSON × 500 000 × facteur Postgres (index, stockage), à mesurer |
| Espace Storage (fichiers finaux) | taille moyenne gzip × 500 000 (JSONL) + taille du CSV complet (gzip) |
| Durée de l'export | 500 pages × temps moyen par page (+ pauses éventuelles imposées par l'API) |

L'ordre de grandeur « ~1 Go » indiqué dans `ADAPTATION_SUPABASE.md` §6 reste **une hypothèse non vérifiée**.

## 5. Règle de fin de pagination retenue (sprint 2) — provisoire et réglable

**Source :** déduction de l'audit (documentation muette sur ce point) et comportement du module 3 actuel.
**Non confirmée par le fournisseur** (questions n°1 et 2). Implémentée dans `bulk_export/api_adapter.py`. Les réglages
sont figés dans la configuration de chaque export (`ExportConfig.pagination`), pour savoir après coup quelle règle a
été appliquée.

| Situation | Réglage | Par défaut | Autre valeur possible |
|---|---|---|---|
| Curseur renvoyé **identique**, page **vide** | — | **Fin normale** | — |
| Curseur renvoyé **identique**, page **avec** des mentions | `on_same_cursor_with_records` | Mentions gardées, puis **fin**, avec un avertissement au journal | `error` |
| Page **vide**, curseur différent ou absent | `on_empty_page` | **Fin**, avec un avertissement au journal | `error` |
| Mentions reçues **sans** curseur suivant | — | **Erreur** (`PaginationError`), jamais une fin | — |
| `status` ≠ `success`, `result` / `docs` absents ou mal formés | — | **Erreur** (`ApiSchemaError`), sans nouvel essai | — |
| HTTP 5xx, délai dépassé, coupure réseau, JSON tronqué | — | Jusqu'à **5 essais** (délais 2 s, 4 s, 8 s, 16 s + hasard), puis erreur | `RetryPolicy` |
| HTTP 429 | — | Attente de `Retry-After` (5 min maximum, sinon abandon), sinon même délai que ci-dessus | `RetryPolicy` |
| HTTP 401 / 403 | — | **Arrêt immédiat**, sans nouvel essai | — |
| Plus de pages que `ceil(nbDocs / rows) × 1,2 + 10` | `page_margin_factor`, `page_margin_extra` | **Erreur** (protection contre une boucle) | |

Quelle que soit la façon dont la pagination s'arrête, **COMPLETED n'est attribué qu'après validation** : nombre de
mentions uniques = `nbDocs`, sinon INCOMPLETE (règle n°5).

## 6. Points à faire confirmer
Voir `questions_fournisseur.md` : points 5, 6, 7, 10, 11, 12, 13 et écarts A, B, C.
