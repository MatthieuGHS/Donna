-- Migration 001: Create todos table
-- Idempotent: safe to run multiple times

CREATE TABLE IF NOT EXISTS todos (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    title text NOT NULL,
    deadline date,
    priority text CHECK (priority IN ('high', 'medium', 'low')) DEFAULT 'medium',
    done boolean DEFAULT false,
    created_at timestamptz DEFAULT now()
);

-- Enable RLS
ALTER TABLE todos ENABLE ROW LEVEL SECURITY;
