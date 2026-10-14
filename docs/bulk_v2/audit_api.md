# Audit de l'API Ratings & Reviews — Sprint 0

> **Statut du document : en attente des informations de l'utilisateur.**
> Le script `scripts/audit_api.py` n'a pas été écrit (décision du 14/10/2026 : l'utilisateur dispose déjà des mesures).
> Statuts possibles pour chaque point : **constaté** (observé sur un petit volume, non garanti) ·
> **confirmé par le fournisseur** · **inconnu**. Aucune valeur n'est remplie sans source.

## Ce que le code existant permet déjà de dire (source : `audit_code.md`)
| Point | Ce que montre le code | Statut |
|---|---|---|
| Paramètre de curseur | Le curseur est envoyé dans `nextCursorMark` (pas `cursorMark`), valeur initiale `*` | constaté dans le code (commentaire `module3_bulk_export.py:404`) |
| Curseur suivant | Lu dans `result.nextCursorMark` | constaté dans le code |
| Mentions | Liste dans `result.docs` | constaté dans le code |
| Volume attendu | `/metrics` → `result.nbDocs` | constaté dans le code |
| Quotas | `/quotas` → `used volume`, `remaining volume`, `quota`, `end date` | constaté dans le code |
| Authentification | Token passé dans l'adresse (`?token=`) | constaté dans le code |

## Points à mesurer (à compléter)
| # | Point | Valeur | Statut | Source |
|---|---|---|---|---|
| 1 | Taille de page maximale acceptée pour `rows` | — | inconnu | |
| 2 | Nom exact du champ identifiant natif (`id` ?) | — | inconnu | |
| 3 | ID présent sur 100 % des mentions de l'échantillon ? | — | inconnu | |
| 4 | Fin de pagination : curseur renvoyé identique ? page vide ? curseur absent ? | — | inconnu | |
| 5 | Ordre des résultats stable entre deux parcours identiques ? | — | inconnu | |
| 6 | En-têtes de quota / `Retry-After` dans les réponses | — | inconnu | |
| 7 | Consommation de quota par appel (par page ? par mention ? une reprise reconsomme-t-elle ?) | — | inconnu | |
| 8 | Temps moyen de réponse par page (et pour quelle valeur de `rows`) | — | inconnu | |
| 9 | Taille moyenne d'une mention (JSON brut, octets) | — | inconnu | |
| 10 | Taille moyenne compressée gzip | — | inconnu | |
| 11 | IDs uniques récupérés vs `nbDocs` de `/metrics` (même filtres) | — | inconnu | |
| 12 | Codes d'erreur observés (401, 429, 5xx) et leur format | — | inconnu | |

## Extrapolation à 500 000 mentions (à calculer à partir des lignes 8 à 10)
| Élément | Calcul | Résultat |
|---|---|---|
| Espace Postgres pendant la collecte | taille brute × 500 000 (+ index, à mesurer) | — |
| Espace Storage (fichiers finaux gzip) | taille gzip × 500 000 | — |
| Durée d'un export complet | (500 000 / `rows`) × temps par page | — |
| Nombre de pages | 500 000 / `rows` | — |

## Règle de fin de pagination retenue
_À rédiger quand les points 4 et 11 sont renseignés. Tant que ce n'est pas confirmé par le fournisseur, la règle
sera configurable dans le moteur (règle n°10 de `CLAUDE.md`)._
