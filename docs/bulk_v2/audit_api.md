# Audit de l'API Ratings & Reviews — Sprint 0

> **Source principale :** « Description de l'API Rating&Reviews pour Pierre Fabre v2.0 », mars 2025, 13 pages
> (fourni par l'utilisateur le 15/10/2026, non commité dans le dépôt).
> **Sources secondaires :** le code existant (`audit_code.md`).
>
> Statuts utilisés :
> - **documenté** : écrit dans la documentation du fournisseur (engagement écrit, mais pas encore vérifié en pratique) ;
> - **constaté** : observé dans le code existant ou lors d'un appel réel (petit volume, non garanti) ;
> - **confirmé par le fournisseur** : réponse explicite à nos questions (`questions_fournisseur.md`) ;
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
| 2 | Champ identifiant natif | **`id`** (chaîne) | documenté (cohérent avec le code : `module3_bulk_export.py:427`) |
| 3 | `id` présent sur 100 % des mentions ? Unique ? Permanent ? | — | **inconnu** |
| 4 | Paramètre et format du curseur | Le curseur se passe dans `nextCursorMark` (curseur de départ `*`, selon le code) et revient dans `result.nextCursorMark`. Il fonctionne aussi en mode `random`. | documenté (paramètre et réponse) · constaté dans le code (`*`) |
| 5 | **Signal de fin de pagination** | Non décrit : curseur identique, page vide ou champ absent ? | **inconnu** |
| 6 | Ordre des résultats stable entre deux parcours ? | Non décrit (sans `random`) | **inconnu** |
| 7 | Durée de validité d'un curseur (reprise après plusieurs heures) | Non décrit | **inconnu** |
| 8 | Décompte du quota | **Seul `/reviews` consomme du quota, à raison du nombre de mentions effectivement renvoyées.** `/metrics` et `/quotas` sont gratuits. | documenté |
| 9 | Une page relue (nouvelle tentative, reprise) est-elle décomptée à nouveau ? | D'après la règle du point 8, **oui** dès qu'une réponse contenant des mentions est renvoyée. Non documenté pour une réponse en erreur. | documenté par déduction · cas d'erreur **inconnu** |
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
- **Quota consommé au minimum : 500 000 mentions.** Chaque reprise ou nouvelle tentative d'une page déjà reçue reconsomme jusqu'à 1 000 mentions.
  ➡️ **Avant de lancer un export, il faut vérifier `remaining volume ≥ nbDocs` (plus une marge).** Sinon, l'export s'arrêtera en cours de route. L'exemple de la documentation montre un quota de 100 000 : si c'est l'ordre de grandeur réel, **un export de 500 000 est impossible** sans augmentation du quota. **À vérifier avec `/quotas`.**
- Le moteur doit **éviter de relire une page déjà sécurisée** : c'est une raison de plus pour enregistrer le point de reprise juste après chaque page.

### Ce qui reste à mesurer
Taille réelle d'une mention et temps de réponse : **inconnus**. Formules à appliquer dès qu'une première page réelle aura été lue (sprint 1, mesure automatique dans le journal d'export) :

| Élément | Formule |
|---|---|
| Espace Postgres pendant la collecte | taille moyenne JSON × 500 000 × facteur Postgres (index, stockage), à mesurer |
| Espace Storage (fichiers finaux) | taille moyenne gzip × 500 000 (JSONL) + taille du CSV complet (gzip) |
| Durée de l'export | 500 pages × temps moyen par page (+ pauses éventuelles imposées par l'API) |

L'ordre de grandeur « ~1 Go » indiqué dans `ADAPTATION_SUPABASE.md` §6 reste **une hypothèse non vérifiée**.

## 5. Règle de fin de pagination proposée (provisoire, configurable)

Puisque la documentation ne décrit pas la fin, le moteur appliquera ceci, en attendant la réponse du fournisseur :

| Situation | Interprétation proposée | Statut final possible |
|---|---|---|
| `nextCursorMark` renvoyé **identique** au curseur envoyé | Fin normale (convention habituelle de ce type de curseur, déjà utilisée par le module 3) | → contrôles de validation |
| Page **vide** (`docs` vide) avec un curseur | Fin probable, **à signaler** dans le journal | → contrôles de validation |
| `nextCursorMark` **absent** alors que `docs` n'est pas vide | **Anomalie** | FAILED (reprenable) |
| `status` ≠ `success`, code HTTP ≠ 200, JSON illisible | **Erreur**, jamais une fin | Nouvelle tentative, puis FAILED |
| Nombre de pages > `nbDocs / rows` + marge | **Anomalie** (protection contre une boucle infinie) | FAILED |

Quelle que soit la façon dont la boucle s'arrête, **COMPLETED n'est attribué qu'après validation** : nombre d'IDs uniques = `nbDocs`. Sinon, le statut est INCOMPLETE (règle n°5).

## 6. Points à faire confirmer
Voir `questions_fournisseur.md` : points 3, 5, 6, 7, 9 (cas d'erreur), 10, 11, 12, 13 et écarts A, B, C.
