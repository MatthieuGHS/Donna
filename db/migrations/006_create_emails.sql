-- Migration 006: Create emails table (Zimbra mail cache)
-- Idempotent: safe to run multiple times
--
-- Rolling window of the 30 most recent emails fetched from Zimbra via IMAP.
-- Synced 3x/day (7h, 12h, 17h). Donna reads from here, never hits Zimbra.

CREATE TABLE IF NOT EXISTS emails (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id text NOT NULL UNIQUE,
    sender_name text,
    sender_email text NOT NULL,
    subject text,
    body text,
    received_at timestamptz NOT NULL,
    notified_in_recap boolean DEFAULT false,
    created_at timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_emails_received_at ON emails (received_at DESC);
CREATE INDEX IF NOT EXISTS idx_emails_notified ON emails (notified_in_recap, received_at DESC)
    WHERE notified_in_recap = false;

-- Enable RLS (deny-all for anon, service_role bypasses via insert/update/select)
ALTER TABLE emails ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Deny all anon access on emails" ON emails;
DROP POLICY IF EXISTS "Service role full access on emails" ON emails;

CREATE POLICY "Deny all anon access on emails"
    ON emails
    FOR ALL
    TO anon
    USING (false)
    WITH CHECK (false);

CREATE POLICY "Service role full access on emails"
    ON emails
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);
