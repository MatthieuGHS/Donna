-- Migration 007: Add display_description and executable columns to pending_actions
-- Idempotent: safe to run multiple times.
--
-- display_description: human-readable text shown to the user on the inline
-- button. Generated server-side from the validated payload + real data fetched
-- from Google Calendar / Supabase, so a compromised model cannot UI-spoof
-- what the user sees on Confirm/Cancel.
--
-- executable: when false, /pending/resolve refuses 'confirm'. Cancel still
-- works so the user can dismiss a pending whose underlying object disappeared.

ALTER TABLE pending_actions
    ADD COLUMN IF NOT EXISTS display_description text;

ALTER TABLE pending_actions
    ADD COLUMN IF NOT EXISTS executable boolean DEFAULT true;

-- Backfill existing rows so legacy pendings remain confirmable.
UPDATE pending_actions
   SET executable = true
 WHERE executable IS NULL;
