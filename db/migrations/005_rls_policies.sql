-- Migration 005: RLS Policies
-- Idempotent: DROP IF EXISTS before CREATE
--
-- Strategy:
-- - The server uses the service_role key which bypasses RLS.
-- - These policies are a SECOND LAYER of defense in case the service_role key leaks.
-- - No anon access is allowed on any table.
-- - Only authenticated service role can access data.

-- =====================
-- TODOS
-- =====================

-- Drop existing policies to make this idempotent
DROP POLICY IF EXISTS "Deny all anon access on todos" ON todos;
DROP POLICY IF EXISTS "Service role full access on todos" ON todos;

-- Deny everything for anon role
CREATE POLICY "Deny all anon access on todos"
    ON todos
    FOR ALL
    TO anon
    USING (false)
    WITH CHECK (false);

-- Allow service_role full access (this is redundant since service_role bypasses RLS,
-- but explicit is better than implicit)
CREATE POLICY "Service role full access on todos"
    ON todos
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

-- =====================
-- RULES
-- =====================

DROP POLICY IF EXISTS "Deny all anon access on rules" ON rules;
DROP POLICY IF EXISTS "Service role full access on rules" ON rules;

CREATE POLICY "Deny all anon access on rules"
    ON rules
    FOR ALL
    TO anon
    USING (false)
    WITH CHECK (false);

CREATE POLICY "Service role full access on rules"
    ON rules
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

-- =====================
-- PENDING_ACTIONS
-- =====================

DROP POLICY IF EXISTS "Deny all anon access on pending_actions" ON pending_actions;
DROP POLICY IF EXISTS "Service role full access on pending_actions" ON pending_actions;

CREATE POLICY "Deny all anon access on pending_actions"
    ON pending_actions
    FOR ALL
    TO anon
    USING (false)
    WITH CHECK (false);

CREATE POLICY "Service role full access on pending_actions"
    ON pending_actions
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

-- =====================
-- AUDIT_LOGS
-- =====================

DROP POLICY IF EXISTS "Deny all anon access on audit_logs" ON audit_logs;
DROP POLICY IF EXISTS "Service role full access on audit_logs" ON audit_logs;

CREATE POLICY "Deny all anon access on audit_logs"
    ON audit_logs
    FOR ALL
    TO anon
    USING (false)
    WITH CHECK (false);

CREATE POLICY "Service role full access on audit_logs"
    ON audit_logs
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);
