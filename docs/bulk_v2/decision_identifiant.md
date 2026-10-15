# Décision — Identifiant d'unicité des mentions (PROPOSITION, à valider)

> Statut : **proposée le 15/10/2026, en attente de validation de l'utilisateur.**
> Elle modifie la règle n°6 de `CLAUDE.md` et la spec §5.3 : rien ne sera codé avant validation.

## 1. Le problème
L'utilisateur indique (15/10/2026) que **l'API ne fournit pas d'identifiant fiable pour un verbatim**.
La documentation montre bien un champ `id` (ex. `"97749480"`), mais ni son unicité ni sa stabilité ne sont garanties.
Le projet Compass (`g00dtim3/mvp_verbatim_import`) avait déjà buté sur ce point : il n'a pas pu confirmer que le
`guid` Semantiweb (c'est-à-dire le `id` de l'API, renommé `guid` par `postprocess_reviews()`) reste stable d'un
export à l'autre. Il l'a donc remplacé par une empreinte calculée.

La règle n°6 actuelle (« pas d'ID natif exploitable = erreur explicite ») ferait donc échouer **tous** les exports.

## 2. Ce que fait Compass (`compass_import/core/hasher.py`, « scénario B »)
```
id = SHA-256( brand + date + product_name + verbatim_content + country + source + rating )
```
- 7 champs, **dans cet ordre figé**, chacun passé en `strip()` puis `lower()`, et collés **sans séparateur** ;
- un champ absent compte comme `""` (une date absente est une erreur) ;
- le `guid` d'origine est gardé à côté, pour l'audit ;
- en base : `ON CONFLICT (id) DO NOTHING`, c'est-à-dire qu'une ligne de même empreinte est ignorée.
- **Limite assumée par Compass** : deux avis réellement différents mais identiques sur ces 7 champs (ex. deux « Parfait »
  5 étoiles, même jour, même produit, même pays, même source) ne donnent qu'**une seule** ligne.

Ce n'est pas un identifiant « inventé » au sens de la règle n°6 : ni compteur, ni UUID, ni numéro de ligne. C'est
une **empreinte des données source**, recalculable par n'importe qui à partir de la mention.

## 3. Pourquoi on ne peut pas copier Compass tel quel
Compass **importe** des fichiers : fusionner deux lignes identiques y est acceptable. Bulk Export V2 **exporte** et
doit prouver sa complétude (spec §7). Si deux avis jumeaux sont fusionnés :
- une mention réelle disparaît, ce qui viole la règle n°7 (« jamais fusionné silencieusement ») ;
- le nombre de mentions uniques passe sous `nbDocs` : l'export finit en INCOMPLETE **sans que rien ne manque vraiment**.

## 4. Proposition pour V2 : deux empreintes
| Empreinte | Calcul | Rôle |
|---|---|---|
| `content_key` | **Exactement la méthode Compass scénario B** (mêmes 7 champs, même ordre, même normalisation) | Clé métier commune avec Compass ; regroupe les avis « semblables » |
| `raw_hash` | SHA-256 de la mention **complète** telle que reçue (JSON aux clés triées, sans aucune modification de valeur) | Distingue une vraie répétition d'un avis jumeau |

Correspondance des champs API → méthode Compass :
`brand` → brand · `date` → date · `product` → product_name · `verbatim content` → verbatim_content ·
`country` → country · `source` → source · `rating` → rating.
(Le nom exact du champ verbatim reste à vérifier sur une vraie réponse, cf. `audit_api.md` écart C.)

### Règles de traitement
| Cas | Ce qui se passe | Compteur |
|---|---|---|
| `raw_hash` jamais vu | Mention écrite | `unique_count` |
| Même `raw_hash` déjà vu (mention strictement identique, tous champs compris) | **Non réécrite**. C'est le cas d'une page renvoyée deux fois par l'API. | `duplicate_count` |
| Même `content_key`, mais `raw_hash` différent | **Les deux sont écrites**, et une ligne de conflit est tracée (les deux empreintes, la page, sans le texte du verbatim dans le journal) | `collision_count`, signalé dans le manifeste et à la validation |
| Date absente ou vide | Erreur explicite (même règle que Compass) | `error_count` |

**Limite qui demeure, à documenter et non à contourner :** deux mentions **identiques sur tous les champs** renvoyés
par l'API ne peuvent pas être distinguées d'une répétition de page. Elles comptent pour une. C'est la même limite
structurelle que Compass, mais réduite à un cas beaucoup plus rare, puisque tous les champs, `id` compris, doivent être égaux.

### Ce qui ne change pas
- Les données brutes (JSONL) restent **intactes** : le champ `id` de l'API est gardé tel quel (règle n°3). Il n'est
  simplement **pas utilisé comme clé**.
- Les empreintes sont des **métadonnées** stockées à côté de la mention, pas des champs ajoutés dans le JSON brut.

## 5. Point à trancher : la date dans `content_key`
Compass calcule son empreinte à partir du **format plat**, où `postprocess_reviews()` a ramené la date au **1er du mois**.
Compass lit ensuite `01/MM/AAAA`, donc ses empreintes sont calculées avec une date au mois près.

| Option | Avantage | Inconvénient |
|---|---|---|
| **A. Date au jour** (`AAAA-MM-JJ` tiré de `2024-11-28T15:45:28Z`) | Plus précise : moins d'avis jumeaux confondus | `content_key` **différent** de l'`id` Compass pour la même mention |
| **B. Date au 1er du mois** (comme Compass aujourd'hui) | `content_key` **identique** à l'`id` Compass : jointure directe entre les deux projets | Plus de collisions (avis semblables du même mois) |

Recommandation : **A** pour `content_key`, avec en option une colonne `compass_id` (option B) dans le seul format
analytique si la jointure avec Compass est utile. À valider.

## 6. Modification proposée de `CLAUDE.md`, règle n°6
> **6. Pas d'identifiant inventé** (compteur, UUID, numéro de ligne). L'unicité repose sur deux empreintes
> SHA-256 calculées **uniquement à partir des champs source** (`content_key` selon la méthode Compass scénario B,
> `raw_hash` sur la mention complète ; cf. `docs/bulk_v2/decision_identifiant.md`). Le champ `id` de l'API est
> conservé tel quel mais n'est pas utilisé comme clé. Une mention sans date = erreur explicite.
