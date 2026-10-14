# Questions au fournisseur de l'API Ratings & Reviews

> Brouillon du 14/10/2026. À affiner avec les mesures de `audit_api.md` avant envoi.
> La question « Hébergement » de la spec §10 est retirée : elle est réglée par `ADAPTATION_SUPABASE.md`.

Bonjour,

Nous préparons un export complet (jusqu'à 500 000 mentions par opération) via `/reviews` avec pagination
par `nextCursorMark`. Pour garantir qu'aucune mention n'est perdue ni dupliquée, pourriez-vous nous confirmer
les points suivants ?

## 1. Pagination
- Le parcours par `nextCursorMark` (curseur initial `*`) est-il garanti de renvoyer **toutes** les mentions
  correspondant aux filtres, chacune **une seule fois** ?
- Quel est l'**ordre** de tri utilisé ? Est-il stable entre deux parcours identiques ?
- Quel est le **signal officiel de fin** : un `nextCursorMark` identique à celui envoyé, une page vide,
  l'absence du champ, ou autre ?
- Quelle est la **valeur maximale** autorisée pour `rows` ?
- Un curseur a-t-il une **durée de validité** ? Peut-on reprendre un parcours plusieurs heures plus tard
  avec un curseur déjà reçu ?
- Le paramètre `random` est-il compatible avec la pagination par curseur ?

## 2. Identifiant
- Le champ `id` est-il **unique et permanent** pour une mention ? Peut-il être absent ?

## 3. Volumétrie
- Avez-vous une estimation de la taille moyenne d'une mention complète (tous champs) ?

## 4. Quotas
- Comment le quota est-il décompté : par appel, par mention renvoyée, par volume ?
- Une page relue (nouvelle tentative après erreur, reprise après interruption) est-elle **décomptée à nouveau** ?
- Quelles limites de débit s'appliquent (appels par seconde / minute) ? La réponse 429 contient-elle `Retry-After` ?

## 5. Stabilité des données
- Les mentions peuvent-elles être ajoutées, modifiées ou supprimées **pendant** un parcours ?
- Le nombre `nbDocs` de `/metrics` est-il calculé exactement avec les mêmes règles que `/reviews` ?
- Existe-t-il un mécanisme de **snapshot** (figer le jeu de données le temps de l'export) ?

## 6. Sécurité
- Est-il possible de passer le token dans un **en-tête HTTP** plutôt que dans l'adresse ?
  (Cela éviterait qu'il apparaisse dans des journaux techniques.)

Merci d'avance,
