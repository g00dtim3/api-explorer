# Décision — Identifiant d'unicité des mentions

> Statut : **validée par l'utilisateur le 15/10/2026.**
> Remplace la règle n°6 initiale de `CLAUDE.md` et précise la spec §5.3.

## 1. Le problème
Le champ `id` de l'API est **présent mais pas fiable** (indiqué par l'utilisateur, 15/10/2026) :
- les `id` sont **générés au moment de l'export par l'API** ;
- **d'un export à l'autre, on retrouve les mêmes valeurs d'`id`**. Un même `id` ne désigne donc pas forcément la même mention.

Conséquences :
- `id` ne peut servir **ni** de clé d'unicité, **ni** de lien entre deux exports ;
- on ne sait pas si un `id` est unique **à l'intérieur** d'un même parcours, ni s'il change quand une page est relue
  (nouvelle tentative, reprise). Le moteur ne doit donc **rien** supposer sur ce champ ;
- dans le module 3 actuel, la déduplication par `id` pourrait jeter de vraies mentions si des `id` se répètent dans un
  même export (à vérifier sur un export réel).

Le projet Compass (`g00dtim3/mvp_verbatim_import`, où l'`id` de l'API s'appelle `guid` après `postprocess_reviews()`)
était arrivé à la même conclusion et utilise une empreinte calculée.

## 2. La méthode Compass (`compass_import/core/hasher.py`, « scénario B »)
```
SHA-256( brand + date + product_name + verbatim_content + country + source + rating )
```
- 7 champs, **dans cet ordre figé**, chacun passé en `str()`, `strip()`, puis `lower()`, et collés **sans séparateur** ;
- un champ absent compte comme `""` ; une date absente est une erreur ;
- encodage UTF-8, résultat en hexadécimal minuscule (64 caractères).

Ce n'est pas un identifiant « inventé » (ni compteur, ni UUID, ni numéro de ligne) : c'est une **empreinte des
données source**, que l'on peut recalculer à partir de la mention.

## 3. Ce qui est retenu pour V2 : trois empreintes

| Empreinte | Calcul | Rôle | Où elle apparaît |
|---|---|---|---|
| `content_key` | Méthode Compass, mais avec la **date au jour** (`AAAA-MM-JJ`, tirée de `2024-11-28T15:45:28Z`) | Regroupe les avis « semblables » ; sert à détecter les jumeaux | Métadonnées, manifeste, format analytique |
| `raw_hash` | SHA-256 de la mention **complète sauf le champ `id`** (JSON aux clés triées, valeurs non modifiées) | **Clé d'unicité** de l'export : distingue une vraie répétition d'un avis jumeau | Métadonnées (base, manifeste) |
| `compass_id` | **Reproduction exacte** de l'`id` Compass (date ramenée **au 1er du mois**, comme le fait le format plat) | Lien futur entre Bulk Export V2 et Compass | **Format analytique uniquement** |

Choix validés :
- **Option A** pour `content_key` (date au jour) **+** `compass_id`, car les deux projets seront reliés à terme.
- `raw_hash` **exclut `id`** : comme l'API génère les `id` à l'export, une même mention relue pourrait revenir avec un
  autre `id`. L'inclure ferait passer une page répétée pour des mentions nouvelles, donc des doublons écrits.
  Ce choix est **réglable** (règle n°10) et pourra être revu si le fournisseur garantit `id` dans un parcours.

### Règles de traitement
| Cas | Ce qui se passe | Compteur |
|---|---|---|
| `raw_hash` jamais vu | Mention écrite | `unique_count` |
| `raw_hash` déjà vu (mêmes valeurs sur tous les champs sauf `id`) | **Non réécrite** : c'est le cas d'une mention renvoyée deux fois. Les deux `id` sont notés dans le journal. | `duplicate_count` |
| Même `content_key`, `raw_hash` différent (ex. attributs ou opinion différents) | **Les deux sont écrites**, et le conflit est tracé : empreintes et page, **sans le texte** du verbatim dans le journal | `collision_count`, signalé dans le manifeste et à la validation |
| Date absente ou illisible | Erreur explicite | `error_count` |

**Limite assumée, documentée et non contournée :** deux avis réellement distincts, identiques sur **tous** les champs
sauf `id`, comptent pour un seul. Ils sont signalés comme doublons, avec leurs deux `id`, et ne disparaissent pas en silence.
Si cela arrive, le nombre de mentions uniques sera inférieur à `nbDocs` et l'export sera INCOMPLETE avec ce motif
explicite. On ne déclare jamais une complétude non démontrée.

### Ce qui ne change pas
- Les données brutes (JSONL) restent **intactes**, `id` compris (règle n°3).
- Les empreintes sont des **métadonnées** stockées à côté de la mention, jamais ajoutées dans le JSON brut.

## 4. Reproduire exactement l'`id` Compass : points de vigilance
`compass_id` doit être **identique, au caractère près**, à ce que Compass calculerait sur le format plat de la même mention.
Correspondance (Compass lit le CSV plat produit par `postprocess_reviews()`) :

| Paramètre Compass | Champ Compass lu | Valeur prise dans la mention API |
|---|---|---|
| brand | `brand` | `brand` |
| date | `date` (format plat `01/MM/AAAA`) | `date` ramenée au 1er du mois, en `AAAA-MM-01` |
| product_name | `product_name_SEMANTIWEB` | `product` |
| verbatim_content | `verbatim_content` | `content trad` (renommé par le format plat) — **voir ci-dessous** |
| country | `country` | `country` |
| source | `source` (vide → `""`) | `source` |
| rating | `rating` converti en entier 1–5, sinon `""` | `rating` |

Points vérifiés au sprint 1 (15/10/2026), en faisant passer de fausses mentions par la chaîne réelle
(format plat de l'application, puis lecture et calcul par le code Compass) :
- ✅ `compass_id` est **identique** à l'`id` Compass sur 3 fausses mentions choisies pour piéger le calcul
  (accents, `&`, `;`, retours à la ligne, note et source vides, verbatim « NA » que pandas lit comme vide).
  Ces valeurs servent de référence dans `tests/test_fingerprints.py`.
- ✅ Correction : si le champ `content trad` est absent, Compass **refuse le fichier entier** (colonne
  `verbatim_content` obligatoire). Il ne calcule donc pas un verbatim vide. `compass_id` vaut alors `None`.
- ⚠️ **Découverte : Compass ne peut pas lire tel quel le format plat de l'application.** Compass exige une colonne
  `sampling` (minuscule), alors que `postprocess_reviews()` produit `Sampling` (majuscule). Pour le test, la colonne a
  été renommée. **Question ouverte :** le fichier que Compass importe vient-il vraiment du « format plat » de
  l'application, éventuellement retouché à la main, ou d'un autre export Semantiweb ? Si ce fichier contient la
  **date au jour**, `compass_id` devrait utiliser le jour et non le 1er du mois. C'est un réglage à changer, pas du
  code à réécrire, mais il faut le savoir avant de relier les deux projets.

Toujours à vérifier sur une vraie réponse : le nom réel du champ verbatim (`verbatim content` ou `content trad`).
Les deux champs utilisés sont **réglables** (`verbatim_field`, `compass_verbatim_field`), figés dans la configuration
de chaque export, et seront inscrits dans le manifeste (sprint 6).

## 5. Règle n°6 de `CLAUDE.md` (nouvelle rédaction)
> **6. Pas d'identifiant inventé** (compteur, UUID, numéro de ligne). Le champ `id` de l'API n'est pas fiable (régénéré
> à chaque export) : il est conservé tel quel mais n'est **jamais** utilisé comme clé. L'unicité repose sur des empreintes
> SHA-256 calculées uniquement à partir des champs source (`raw_hash`, `content_key`, `compass_id` ; cf.
> `docs/bulk_v2/decision_identifiant.md`). Une mention sans date = erreur explicite.
