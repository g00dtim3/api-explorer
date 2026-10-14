# Sprint 2 — Client API robuste et adaptateur de pagination

**But :** un appel API qui ne plante pas au premier incident réseau, et une couche qui décrit
proprement « page suivante / fin / erreur », sans que le reste du code connaisse `nextCursorMark`.
Spec : §5.1, §5.5, §8 (APIClient, adaptateur).
Dépend de : sprint 0 (limites et règle de fin confirmées dans `audit_api.md`).

## En une phrase
On distingue clairement trois situations : « il y a une page », « c'est vraiment fini », « quelque chose ne va pas ».
L'ancien code les confondait parfois.

## Tâches
1. `api_client.py` — modifications **rétrocompatibles uniquement** (les appels existants doivent marcher à l'identique) :
   - Paramètre optionnel de timeout (connexion, lecture) avec valeurs par défaut sûres.
   - Exceptions typées : `ApiAuthError` (401/403), `ApiRateLimitError` (429, avec `retry_after`),
     `ApiTransientError` (5xx, timeout, coupure réseau), `ApiClientError` (autres 4xx), `ApiSchemaError`.
   - Si le module existant attend l'ancien comportement (ex. retour `None` en cas d'erreur), ajouter une
     **nouvelle** méthode (ex. `get_reviews_strict`) plutôt que changer l'ancienne.
   - Aucun token dans les messages d'exception.
2. `bulk_export/retry.py` : tentatives limitées (configurable, ex. 5), backoff exponentiel + jitter,
   respect de `Retry-After` sur 429, aucune nouvelle tentative sur erreur d'authentification ou de schéma.
   Chaque tentative est journalisée (sans secret).
3. `bulk_export/api_adapter.py` — contrat générique :
   ```python
   class PageResult:            # dataclass
       records: list[dict]      # mentions brutes, non modifiées
       cursor_sent: str         # curseur qui a servi à lire cette page
       next_cursor: str | None  # curseur pour la page suivante
       is_last: bool            # fin CONFIRMÉE selon le contrat de l'API
       raw_meta: dict           # infos utiles (total annoncé, quota…) sans secret

   class PaginationAdapter(Protocol):
       def initial_cursor(self) -> str: ...
       def fetch_page(self, params: dict, cursor: str) -> PageResult: ...
       def expected_count(self, params: dict) -> int: ...      # via /metrics
       def quota(self) -> dict | None: ...
       def record_id(self, record: dict) -> str: ...           # lève une erreur si ID absent
   ```
   - Implémentation `RatingsReviewsAdapter` basée sur `nextCursorMark`.
   - Règle de fin **issue de `audit_api.md`** (ex. curseur renvoyé == curseur envoyé). Cas à distinguer :
     fin normale / page vide inattendue / curseur répété avec des données / réponse sans curseur → erreur, pas fin.
   - Validation de schéma minimale : la réponse contient la liste attendue et chaque mention a un ID.
   - `build_filter_params()` réutilisé pour `/reviews` **et** `/metrics` afin d'avoir les mêmes filtres ;
     `random` forcé à désactivé.
   - Limite d'itérations : `ceil(expected / rows) × marge` (marge configurable, ex. 1,2 + 10), à la place des 1 000 fixes.

## Tests (`tests/test_api_adapter.py`, `tests/test_retry.py`) — avec un faux client `fake_api_client`
- 429 avec `Retry-After: 3` → attente respectée (temps simulé, pas de vrai `sleep`).
- 503 puis succès → résultat obtenu ; 503 permanent → `ApiTransientError` après N essais.
- 401 → arrêt immédiat, aucune nouvelle tentative.
- Fin normale reconnue ; page vide inattendue et curseur absent → erreur, pas fin.
- Mention sans ID → erreur explicite.
- Le module 3 existant fonctionne toujours (test d'import + appel avec le faux client).

## Ne pas faire
- Ne pas modifier `module3_bulk_export.py`.
- Ne pas coder en dur une règle de fin non confirmée : la rendre configurable et le signaler dans le journal.

## Définition de terminé
- [ ] Tous les tests passent, anciens compris.
- [ ] `JOURNAL.md` liste la règle de fin retenue et sa source (audit / fournisseur).
