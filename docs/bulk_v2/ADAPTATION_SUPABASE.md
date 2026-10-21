# Adaptation de la spécification à l'hébergement Streamlit Cloud + Supabase Pro

> Ce document complète `SPEC.md`. En cas de contradiction, **ce document fait foi** pour les points listés ici ;
> tout le reste de la spec s'applique tel quel.
> Décision prise le 14/10/2026 : pas de serveur ni de VM disponibles ; compte Supabase **Pro** disponible.

## 1. Contexte
- L'application tourne sur **Streamlit Community Cloud** : disque temporaire (effacé au redémarrage),
  application qui peut redémarrer ou s'endormir, pas de processus séparé supervisé.
- **Supabase Pro** fournit une base PostgreSQL permanente et un espace de fichiers (Storage) permanent.

## 2. Écarts par rapport à la spec

| Spec | Version initiale | Adaptation retenue | Pourquoi |
|---|---|---|---|
| §6.1 Stockage | Dossier local `exports/` + SQLite | **Postgres Supabase** (état, points de reprise, mentions brutes en cours de collecte) + **Supabase Storage** (fichiers finaux) | Le disque de Streamlit Cloud est effacé au redémarrage. |
| §5.2 Écriture des lots | JSONL écrit au fil de l'eau sur disque | Chaque mention brute est **insérée dans Postgres** dans la même transaction que le point de reprise. Les lots JSONL (`batch_0001.jsonl.gz`…) sont **fabriqués à la fin** à partir de la base, puis envoyés dans Storage avec leur SHA-256. | Une seule transaction = « données + point de reprise » tout ou rien. Plus besoin de nettoyer des lignes orphelines après un plantage. |
| §5.4 Point de reprise | `fsync` puis commit SQLite | **Commit Postgres** de la page entière (mentions + IDs + compteurs + curseur) | La durabilité est garantie par Postgres. |
| §5.6 Worker | Processus Python supervisé, indépendant | **V1 : tâche en arrière-plan dans l'application Streamlit**, avec un « bail » (heartbeat) dans Postgres. Si l'application redémarre, l'export passe en PAUSED et se **reprend d'un clic**, sans perte. Le moteur reste lançable en ligne de commande (`python -m bulk_export.run`) pour permettre **plus tard** un worker GitHub Actions (sprint 8, optionnel). | Pas de serveur disponible. |
| §4.5 Téléchargements | Fichier local servi par Streamlit | Fichiers dans un **bucket privé** Supabase, téléchargés via un **lien signé temporaire** | Évite de charger 500k lignes dans la mémoire de Streamlit. |
| §4.5 Rétention | Nettoyage des dossiers locaux | **Depuis le lot 1A (21/10/2026)** : les lignes `raw_mentions` sont **conservées** après COMPLETED (purge seulement si `purge_raw_after_validation = true`) et les fichiers Storage ne sont **jamais** supprimés quand `retention_days = 0` (défaut). La taille de la base est surveillée dans Export History. Voir `decision_conservation_brut.md`. *(Avant : brut effacé dès COMPLETED, fichiers supprimés après 30 jours.)* | Le brut est la seule source complète (le format plat retire `content origin` et ramène la date au mois). Espace surveillé (8 Go inclus). |

## 3. Ce qui ne change pas
Toutes les règles de `CLAUDE.md` : données source intactes, pas d'ID artificiel, conflits tracés, COMPLETED
uniquement après validation, aucun secret dans les logs ou fichiers, pas de données inventées, `random` désactivé.

## 4. Limite assumée de la V1 (à afficher dans l'interface)
L'export avance **tant que l'application Streamlit est en marche**. Fermer l'onglet ne l'arrête pas nécessairement,
mais un redémarrage, un redéploiement ou une mise en veille de l'application l'interrompt. Dans ce cas, aucune donnée
validée n'est perdue : l'export reprend au dernier point de reprise quand on clique sur « Reprendre ».

## 5. Paramètres de connexion (secrets Streamlit, jamais dans le code ni dans Git)
```toml
# .streamlit/secrets.toml  (et dans les "Secrets" de Streamlit Cloud)
[bulk_export]
database_url = "postgresql://...pooler.supabase.com:5432/postgres"   # "Session pooler" (compatible IPv4)
supabase_url = "https://<projet>.supabase.co"
supabase_service_key = "..."     # clé service_role : côté serveur uniquement
storage_bucket = "bulk-exports"  # bucket PRIVÉ
retention_days = 0               # 0 = ne jamais supprimer les fichiers (lot 1A)
```
- Utiliser la chaîne de connexion **Session pooler** de Supabase (la connexion directe peut nécessiter IPv6).
- Projet Supabase en **région UE** (les verbatims peuvent contenir des données personnelles).
- Tables dans un schéma dédié `bulk_export` (pas `public`), RLS activé sans politique publique :
  rien n'est accessible via l'API publique de Supabase.

## 6. Volumétrie à vérifier au sprint 0
Taille moyenne d'une mention × 500 000 → espace Postgres pendant la collecte + espace Storage pour les fichiers finaux.
Ordre de grandeur attendu : environ 1 Go par export de 500k (à mesurer, pas à supposer).
