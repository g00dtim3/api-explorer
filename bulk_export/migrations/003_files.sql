-- ═══════════════════════════════════════════════════════════════
-- Bulk Export V2 — Migration 003 : fichiers finaux et rétention (sprint 6)
--
-- À exécuter dans l'éditeur SQL de Supabase APRÈS 001 et 002. Rejouable sans danger.
-- ═══════════════════════════════════════════════════════════════

BEGIN;

-- Empreinte et taille du contenu NON compressé (en plus de celles du fichier envoyé).
ALTER TABLE bulk_export.files ADD COLUMN IF NOT EXISTS content_sha256 TEXT
    CHECK (content_sha256 IS NULL OR length(content_sha256) = 64);
ALTER TABLE bulk_export.files ADD COLUMN IF NOT EXISTS content_bytes BIGINT;

-- Rétention : mentions effacées de la base après COMPLETED ; fichiers supprimés de Storage après expiration.
ALTER TABLE bulk_export.exports ADD COLUMN IF NOT EXISTS raw_purged_at TIMESTAMPTZ;
ALTER TABLE bulk_export.exports ADD COLUMN IF NOT EXISTS files_expired_at TIMESTAMPTZ;

COMMIT;
