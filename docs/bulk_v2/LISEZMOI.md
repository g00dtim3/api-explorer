# LISEZMOI — Mise en place de Bulk Export V2

> Les étapes que **vous** devez faire à la main. Aucune clé, aucun mot de passe ne doit être écrit
> dans le dépôt Git : uniquement dans les « Secrets » de Streamlit ou dans votre fichier local
> `.streamlit/secrets.toml` (ignoré par Git).

## 1. Préparer Supabase (sprint 1)

### 1.1 Vérifier le projet
- Utiliser un projet Supabase **Pro**, en **région UE** (les verbatims peuvent contenir des données personnelles).
  La région se choisit à la création du projet et ne se change pas ensuite : en cas de doute, regardez la
  page d'accueil du projet ou *Project Settings → General*.

### 1.2 Récupérer la chaîne de connexion « Session pooler »
1. Dans le projet, cliquez sur **Connect** (en haut de la page).
2. Choisissez l'onglet de connexion directe à la base, puis la ligne **Session pooler**
   (compatible IPv4, ce dont Streamlit Cloud a besoin).
3. Copiez la chaîne, qui ressemble à
   `postgresql://postgres.<projet>:[YOUR-PASSWORD]@aws-0-eu-....pooler.supabase.com:5432/postgres`.
4. Remplacez `[YOUR-PASSWORD]` par le mot de passe de la base.
   ⚠️ Si le mot de passe contient des caractères spéciaux (`@`, `:`, `/`, `#`, `%`…), il faut les **encoder**
   (`@` devient `%40`, `#` devient `%23`…), sinon la connexion échoue. Le plus simple est de choisir un mot de passe
   composé seulement de lettres et de chiffres (*Project Settings → Database → Reset database password*).

### 1.3 Créer les tables
1. Ouvrez **SQL Editor** → **New query**.
2. Copiez-collez **tout** le contenu de `bulk_export/migrations/001_init.sql`.
3. Cliquez sur **Run**. Le message attendu est « Success. No rows returned ».
4. Vérification : dans **Table Editor**, choisissez le schéma `bulk_export` dans la liste déroulante.
   Six tables doivent apparaître : `exports`, `pages`, `raw_mentions`, `conflicts`, `events`, `files`.

Le script peut être relancé sans danger : il ne recrée pas ce qui existe déjà et n'efface rien.

**Scripts suivants**, à exécuter de la même façon, dans l'ordre, une seule fois chacun :

| Script | Ajouté au | Ce qu'il crée | Vérification |
|---|---|---|---|
| `bulk_export/migrations/002_rejected.sql` | sprint 3 | Table `rejected_mentions` : mentions rejetées (ex. sans date), gardées telles quelles | 7 tables dans le schéma `bulk_export` |

### 1.4 Ne PAS exposer le schéma dans l'API publique
Dans *Project Settings → Data API* (ou *API*), la liste **Exposed schemas** ne doit **pas** contenir `bulk_export`.
Par défaut, elle ne contient que `public` et `graphql_public` : n'y touchez pas.
(Même en cas d'erreur, la sécurité RLS sans politique bloque l'accès, mais deux protections valent mieux qu'une.)

### 1.5 Renseigner les secrets de l'application
Sur **Streamlit Cloud** : votre application → **Settings** → **Secrets**. En local : fichier `.streamlit/secrets.toml`.
Ajoutez la section suivante, sous la section `[api]` existante :

```toml
[bulk_export]
database_url = "postgresql://postgres.<projet>:<mot-de-passe>@aws-0-eu-....pooler.supabase.com:5432/postgres"
# Les lignes suivantes ne servent qu'à partir du sprint 6 (fichiers dans Storage) :
supabase_url = "https://<projet>.supabase.co"
supabase_service_key = "..."      # clé service_role : JAMAIS dans le code ni dans Git
storage_bucket = "bulk-exports"   # bucket PRIVÉ
retention_days = 30
auto_resume = false             # true = relancer seul un export interrompu (cf. EXECUTION.md)
```

Le token de l'API n'a pas besoin d'être recopié : Bulk Export V2 lit le même `[api] token` que le reste de l'application.

Pour la ligne de commande (plus tard), les mêmes valeurs peuvent être données par les variables d'environnement
`BULK_EXPORT_API_TOKEN`, `BULK_EXPORT_DATABASE_URL`, `BULK_EXPORT_DB_SCHEMA`, `BULK_EXPORT_SUPABASE_URL`, `BULK_EXPORT_SUPABASE_SERVICE_KEY`,
`BULK_EXPORT_STORAGE_BUCKET` et `BULK_EXPORT_RETENTION_DAYS`.

## 2. Lancer les tests (pour un développeur)
```bash
pip install -r requirements-dev.txt
pytest                      # tests sans base : les tests « base de données » sont sautés
```
Pour lancer aussi les tests sur une base, il faut une base Postgres **de test**, jamais celle de production.
Les tests effacent et recréent le schéma `bulk_export_test` à chaque fois :
```bash
export BULK_EXPORT_TEST_DATABASE_URL="postgresql://postgres@127.0.0.1:5432/postgres"
pytest
```
