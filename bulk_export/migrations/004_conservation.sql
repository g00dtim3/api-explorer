-- ═══════════════════════════════════════════════════════════════
-- Bulk Export V2 — Migration 004 : conservation du brut (lot 1A)
--
-- À exécuter dans l'éditeur SQL de Supabase APRÈS 001, 002 et 003. Rejouable sans danger.
-- Ne touche qu'au schéma bulk_export.
-- ═══════════════════════════════════════════════════════════════

BEGIN;

-- Le brut reste en base après COMPLETED : retrouver la mention brute d'un verbatim Compass
-- (compass_id = id calculé par compass_import/core/hasher.py) doit être rapide (lot 4).
CREATE INDEX IF NOT EXISTS raw_mentions_compass_id_idx ON bulk_export.raw_mentions (compass_id);

COMMIT;
