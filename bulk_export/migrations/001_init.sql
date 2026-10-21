-- ═══════════════════════════════════════════════════════════════
-- Bulk Export V2 — Migration 001 : schéma initial
--
-- À exécuter UNE fois dans l'éditeur SQL de Supabase (cf. docs/bulk_v2/LISEZMOI.md).
-- Rejouable sans danger : tout est en « IF NOT EXISTS ».
-- Les tests exécutent ce même fichier dans un schéma séparé (le mot bulk_export
-- y est remplacé par bulk_export_test) : ne pas écrire ce mot ailleurs que pour le schéma.
--
-- Sécurité : RLS activé sur chaque table, AUCUNE politique → rien n'est lisible via
-- l'API publique de Supabase. Seule la connexion Postgres de l'application y accède.
-- ═══════════════════════════════════════════════════════════════

BEGIN;

CREATE SCHEMA IF NOT EXISTS bulk_export;

-- ── exports : une ligne par opération d'export (son « état ») ──────────
CREATE TABLE IF NOT EXISTS bulk_export.exports (
    export_id              TEXT PRIMARY KEY
                           CHECK (export_id ~ '^exp_[0-9]{8}T[0-9]{6}Z_[0-9a-f]{8}$'),
    name                   TEXT NOT NULL,
    config_json            JSONB NOT NULL,
    config_hash            TEXT NOT NULL CHECK (length(config_hash) = 64),
    status                 TEXT NOT NULL DEFAULT 'PENDING'
                           CHECK (status IN ('PENDING','RUNNING','STOPPING','PAUSED','FAILED',
                                             'INCOMPLETE','VALIDATING','COMPLETED')),
    expected_count         BIGINT CHECK (expected_count >= 0),       -- nbDocs annoncé par /metrics
    retrieved_count        BIGINT NOT NULL DEFAULT 0,                -- mentions reçues (doublons compris)
    unique_count           BIGINT NOT NULL DEFAULT 0,                -- mentions enregistrées
    duplicate_count        BIGINT NOT NULL DEFAULT 0,                -- même raw_hash reçu à nouveau
    collision_count        BIGINT NOT NULL DEFAULT 0,                -- même content_key, contenu différent
    error_count            BIGINT NOT NULL DEFAULT 0,                -- mentions refusées (ex. sans date)
    pages_count            INTEGER NOT NULL DEFAULT 0,               -- pages API validées
    last_cursor_sent       TEXT,          -- curseur qui a servi à lire la dernière page validée
    last_committed_cursor  TEXT,          -- curseur reçu avec cette page = point de reprise
    pagination_finished    BOOLEAN NOT NULL DEFAULT FALSE,
    batch_index            INTEGER NOT NULL DEFAULT 0,               -- dernier lot de fichier validé
    stop_requested         BOOLEAN NOT NULL DEFAULT FALSE,
    lease_owner            TEXT,          -- exécutant qui tient l'export
    lease_expires_at       TIMESTAMPTZ,
    error_details          JSONB,         -- diagnostic, sans secret
    validation_json        JSONB,         -- résultat des contrôles qualité
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at            TIMESTAMPTZ
);

-- ── pages : une ligne par page API validée ──────────────────────────────
CREATE TABLE IF NOT EXISTS bulk_export.pages (
    export_id         TEXT NOT NULL REFERENCES bulk_export.exports(export_id) ON DELETE CASCADE,
    page_no           INTEGER NOT NULL CHECK (page_no >= 1),
    cursor_sent       TEXT NOT NULL,
    cursor_received   TEXT,
    records_count     INTEGER NOT NULL,   -- mentions présentes dans la réponse
    new_count         INTEGER NOT NULL,
    duplicate_count   INTEGER NOT NULL,
    collision_count   INTEGER NOT NULL,
    error_count       INTEGER NOT NULL,
    committed_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (export_id, page_no)
);

-- ── raw_mentions : les mentions brutes, telles que reçues ───────────────
-- mention_id = raw_hash (empreinte de la mention sans `id`). La clé primaire rend
-- physiquement impossible l'enregistrement d'une même mention deux fois.
CREATE TABLE IF NOT EXISTS bulk_export.raw_mentions (
    export_id     TEXT NOT NULL REFERENCES bulk_export.exports(export_id) ON DELETE CASCADE,
    mention_id    TEXT NOT NULL CHECK (length(mention_id) = 64),
    seq           BIGINT NOT NULL,          -- ordre d'arrivée (1, 2, 3…)
    page_no       INTEGER NOT NULL,
    raw_json      TEXT NOT NULL,            -- texte JSON reçu, jamais modifié
    content_key   TEXT NOT NULL CHECK (length(content_key) = 64),
    compass_id    TEXT CHECK (compass_id IS NULL OR length(compass_id) = 64),
    api_id        TEXT,                     -- copie du champ `id` de l'API (traçabilité, jamais une clé)
    PRIMARY KEY (export_id, mention_id),
    UNIQUE (export_id, seq)
);
CREATE INDEX IF NOT EXISTS raw_mentions_content_key_idx
    ON bulk_export.raw_mentions (export_id, content_key);

-- ── conflicts : doublons et collisions (jamais de texte de verbatim ici) ──
CREATE TABLE IF NOT EXISTS bulk_export.conflicts (
    conflict_no       BIGSERIAL PRIMARY KEY,   -- numéro de ligne du journal (pas un id de mention)
    export_id         TEXT NOT NULL REFERENCES bulk_export.exports(export_id) ON DELETE CASCADE,
    kind              TEXT NOT NULL CHECK (kind IN ('duplicate', 'collision')),
    mention_id        TEXT NOT NULL,           -- raw_hash de la mention concernée
    other_mention_id  TEXT,                    -- collision : raw_hash de l'avis jumeau déjà enregistré
    api_id            TEXT,                    -- doublon : `id` API de la copie écartée
    content_key       TEXT,
    page_no           INTEGER NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS conflicts_export_idx ON bulk_export.conflicts (export_id, conflict_no);

-- ── events : journal court affiché dans l'onglet Monitor ─────────────────
CREATE TABLE IF NOT EXISTS bulk_export.events (
    event_no     BIGSERIAL PRIMARY KEY,
    export_id    TEXT REFERENCES bulk_export.exports(export_id) ON DELETE CASCADE,
    level        TEXT NOT NULL CHECK (level IN ('DEBUG','INFO','WARNING','ERROR')),
    message      TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS events_export_idx ON bulk_export.events (export_id, event_no DESC);

-- ── files : fichiers finaux déposés dans Supabase Storage ───────────────
CREATE TABLE IF NOT EXISTS bulk_export.files (
    export_id    TEXT NOT NULL REFERENCES bulk_export.exports(export_id) ON DELETE CASCADE,
    path         TEXT NOT NULL,
    kind         TEXT NOT NULL,              -- ex. batch_jsonl, csv_complete, zip, manifest
    rows_count   BIGINT,
    sha256       TEXT CHECK (sha256 IS NULL OR length(sha256) = 64),
    size_bytes   BIGINT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (export_id, path)
);

-- ── Sécurité : RLS sans politique sur toutes les tables ─────────────────
ALTER TABLE bulk_export.exports      ENABLE ROW LEVEL SECURITY;
ALTER TABLE bulk_export.pages        ENABLE ROW LEVEL SECURITY;
ALTER TABLE bulk_export.raw_mentions ENABLE ROW LEVEL SECURITY;
ALTER TABLE bulk_export.conflicts    ENABLE ROW LEVEL SECURITY;
ALTER TABLE bulk_export.events       ENABLE ROW LEVEL SECURITY;
ALTER TABLE bulk_export.files        ENABLE ROW LEVEL SECURITY;

-- Retirer tout droit aux rôles publics de Supabase (s'ils existent : absents hors Supabase).
DO $$
DECLARE r TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON SCHEMA bulk_export FROM %I', r);
            EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA bulk_export FROM %I', r);
            EXECUTE format('REVOKE ALL ON ALL SEQUENCES IN SCHEMA bulk_export FROM %I', r);
        END IF;
    END LOOP;
END $$;

COMMIT;
