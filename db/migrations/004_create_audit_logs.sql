-- Migration 004: Create audit_logs table
-- Idempotent: safe to run multiple times

CREATE TABLE IF NOT EXISTS audit_logs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    endpoint text NOT NULL,
    payload jsonb,
    result text CHECK (result IN ('success', 'error')),
    error_message text,
    created_at timestamptz DEFAULT now()
);

-- Enable RLS
ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;

-- Index for efficient log queries by date
CREATE INDEX IF NOT EXISTS idx_audit_logs_created_at ON audit_logs (created_at DESC);
