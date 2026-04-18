-- Migration 002: Create rules table
-- Idempotent: safe to run multiple times

CREATE TABLE IF NOT EXISTS rules (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    type text CHECK (type IN ('availability', 'recap')) NOT NULL,
    rule_text text NOT NULL,
    structured jsonb NOT NULL,
    active boolean DEFAULT true,
    created_at timestamptz DEFAULT now()
);

-- Enable RLS
ALTER TABLE rules ENABLE ROW LEVEL SECURITY;
