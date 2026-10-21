-- ═══════════════════════════════════════════════════════════════
-- Bulk Export V2 — Migration 002 : mentions rejetées
--
-- Une mention que le moteur ne peut pas enregistrer normalement (ex. sans date) n'est
-- jamais jetée : elle est gardée ICI, telle quelle, avec la raison du rejet.
-- Elle est comptée dans exports.error_count et empêche le statut COMPLETED (validation).
--
-- À exécuter dans l'éditeur SQL de Supabase APRÈS 001_init.sql. Rejouable sans danger.
-- ═══════════════════════════════════════════════════════════════

BEGIN;

CREATE TABLE IF NOT EXISTS bulk_export.rejected_mentions (
    reject_no    BIGSERIAL PRIMARY KEY,     -- numéro de ligne du journal (pas un id de mention)
    export_id    TEXT NOT NULL REFERENCES bulk_export.exports(export_id) ON DELETE CASCADE,
    page_no      INTEGER NOT NULL,
    reason       TEXT NOT NULL,             -- ex. « Mention sans date. »
    raw_json     TEXT NOT NULL,             -- texte JSON reçu, jamais modifié
    api_id       TEXT,                      -- copie du champ `id` de l'API (traçabilité)
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS rejected_mentions_export_idx
    ON bulk_export.rejected_mentions (export_id, reject_no);

ALTER TABLE bulk_export.rejected_mentions ENABLE ROW LEVEL SECURITY;

DO $$
DECLARE r TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON bulk_export.rejected_mentions FROM %I', r);
            EXECUTE format('REVOKE ALL ON SEQUENCE bulk_export.rejected_mentions_reject_no_seq FROM %I', r);
        END IF;
    END LOOP;
END $$;

COMMIT;
