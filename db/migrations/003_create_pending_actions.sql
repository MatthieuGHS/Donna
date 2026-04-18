-- Migration 003: Create pending_actions table
-- Idempotent: safe to run multiple times

CREATE TABLE IF NOT EXISTS pending_actions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    action_payload jsonb NOT NULL,
    description text NOT NULL,
    status text CHECK (status IN ('pending', 'resolved', 'cancelled', 'expired')) DEFAULT 'pending',
    expires_at timestamptz NOT NULL,
    resolved_at timestamptz,
    created_at timestamptz DEFAULT now()
);

-- Enable RLS
ALTER TABLE pending_actions ENABLE ROW LEVEL SECURITY;

-- Index for efficient pending action queries
CREATE INDEX IF NOT EXISTS idx_pending_actions_status ON pending_actions (status) WHERE status = 'pending';
