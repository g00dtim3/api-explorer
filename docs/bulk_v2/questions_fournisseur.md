# Questions au fournisseur de l'API Ratings & Reviews

> Version du 15/10/2026, établie à partir de la documentation « Description de l'API Rating&Reviews pour Pierre Fabre v2.0 » (mars 2025).
> Les points déjà couverts par cette documentation ont été retirés (taille maximale de `rows`, endpoints qui consomment du quota),
> ainsi que les questions de quota (compte sans limite depuis le 15/10/2026). Numérotation conservée.
> La question « Hébergement » de la spec §10 est retirée : elle est réglée par `ADAPTATION_SUPABASE.md`.
> Une fois les réponses reçues, les reporter dans `audit_api.md` avec le statut « confirmé par le fournisseur ».

---

Bonjour,

Nous préparons un export complet (jusqu'à 500 000 reviews par opération) via `GET /reviews`, avec `rows=1000` et la
pagination par `nextCursorMark`, **sans** le paramètre `random`. Notre objectif est de garantir qu'aucune review n'est
perdue ni dupliquée, et de pouvoir reprendre un export interrompu. Votre documentation v2.0 (mars 2025) nous a
été très utile. Pourriez-vous nous préciser les points suivants ?

## 1. Pagination
1. Un parcours complet par `nextCursorMark` (en commençant par `*`) renvoie-t-il bien **toutes** les reviews
   correspondant aux filtres, **chacune une seule fois** ?
2. Quel est le **signal officiel de fin** de parcours : un `nextCursorMark` identique à celui envoyé, une liste `docs`
   vide, l'absence du champ `nextCursorMark`, ou autre ?
3. Sans `random`, l'**ordre** des résultats est-il stable entre deux parcours identiques ? Sur quel critère de tri ?
4. Un `nextCursorMark` reste-t-il **valable dans le temps** ? Peut-on reprendre un parcours plusieurs heures,
   ou plusieurs jours, plus tard avec un curseur déjà reçu ?
5. Y a-t-il une limite au nombre total de reviews accessibles par un même parcours ?

## 2. Identifiant
6. Le champ `id` est-il **toujours présent**, **unique** et **permanent** (il ne change jamais pour une même review) ?
   *(Nous avons constaté qu'il n'est pas exploitable comme identifiant. Une réponse positive nous permettrait de simplifier notre traitement.)*

## 3. Champs renvoyés
7. La documentation liste le champ `verbatim content`. Nous observons dans notre code les champs `content trad` et
   `content origin`. Quelle est la **liste à jour** des champs renvoyés par `/reviews` ? Des champs peuvent-ils être
   ajoutés sans préavis ?

## 4. Débit
8. *(retirée : quota illimité)*
9. Quelles **limites de débit** s'appliquent (nombre d'appels par seconde ou par minute) ? En cas de dépassement,
   quel code HTTP est renvoyé, et la réponse contient-elle un en-tête `Retry-After` ?
10. *(retirée : quota illimité)*

## 5. Erreurs
11. Quels **codes HTTP** et quelles valeurs de `status` (autres que `"success"`) l'API peut-elle renvoyer, et sous quel format ?

## 6. Stabilité des données
12. Les reviews peuvent-elles être ajoutées, modifiées ou supprimées **pendant** un parcours ?
13. Le `nbDocs` de `/metrics` est-il calculé exactement avec les mêmes règles que le parcours `/reviews` ? Doit-il
    être strictement égal au nombre d'`id` uniques récupérés ?
14. Existe-t-il un mécanisme de **snapshot** pour figer le jeu de données le temps d'un export ?

## 7. Précisions sur la documentation
15. **Format des dates** `start-date` / `end-date` : le texte indique `YYYY-DD-MM`, mais les exemples utilisent
    `YYYY-MM-DD` (ex. `2024-06-30`). Lequel est le bon ? Les bornes sont-elles **incluses** ? À quelle date de la
    review s'appliquent-elles, et dans quel fuseau horaire ?
16. **Valeurs multiples** : la page 2 indique qu'un filtre ne peut contenir qu'une seule valeur, la page 3 décrit des
    valeurs multiples séparées par des virgules. Pouvez-vous confirmer que les valeurs multiples sont acceptées ?
    Comment filtrer une valeur qui contient elle-même une virgule ?

## 8. Sécurité
17. Est-il possible de transmettre le token dans un **en-tête HTTP** plutôt que dans l'adresse ? Cela éviterait
    qu'il apparaisse dans des journaux techniques.

Merci d'avance,
