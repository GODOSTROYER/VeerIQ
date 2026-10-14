-- 006: the audit trail is append-only, and a task grant's scope is frozen below the application.
--
-- A. runtime.events feeds the hash-chained, signed evidence export. Its only writer is events.py
--    emit() (INSERT). Nothing UPDATEs, DELETEs or TRUNCATEs it, so the triggers below refuse all three.
--    runtime.receipts is INSERT-only (executor.py, import_recovery/adapter.py) and is guarded the same way.
--    runtime.decisions is deliberately NOT guarded: dispatch.py (deciding-block update) UPDATEs it.
--    Unlike recovery.forbid_snapshot_mutation (001_schema.sql) there is no fixture-reset exception:
--    the demo reset never clears these tables, so the refusal is unconditional.
--
-- B. runtime.task_grants.body is the whole TaskGrant. Legitimate code rewrites only these body keys:
--      status, commits_used   executor.py (commit), grants.py authorize()
--      expires_at             grants.py authorize(), verification/checks.py expired_grant
--      authorized_at, authorized_by, grant_digest   grants.py authorize()
--    Every other body key is frozen. The column-level rules block the same escalation through columns
--    that the commit role holds UPDATE on (002_executor_hardening.sql): max_commits never changes,
--    commits_used never decreases, and status can only become active from active (a commit that
--    leaves it active) or from draft with authorized_by and authorized_at set. authorize() sets both
--    in the same statement; the commit role holds no UPDATE on those columns, so it cannot activate
--    a draft grant itself.

CREATE OR REPLACE FUNCTION runtime.forbid_evidence_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'runtime.% is append-only (attempted %)', TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'insufficient_privilege';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS events_append_only ON runtime.events;
CREATE TRIGGER events_append_only BEFORE UPDATE OR DELETE ON runtime.events
    FOR EACH ROW EXECUTE FUNCTION runtime.forbid_evidence_mutation();
DROP TRIGGER IF EXISTS events_no_truncate ON runtime.events;
CREATE TRIGGER events_no_truncate BEFORE TRUNCATE ON runtime.events
    FOR EACH STATEMENT EXECUTE FUNCTION runtime.forbid_evidence_mutation();

DROP TRIGGER IF EXISTS receipts_append_only ON runtime.receipts;
CREATE TRIGGER receipts_append_only BEFORE UPDATE OR DELETE ON runtime.receipts
    FOR EACH ROW EXECUTE FUNCTION runtime.forbid_evidence_mutation();
DROP TRIGGER IF EXISTS receipts_no_truncate ON runtime.receipts;
CREATE TRIGGER receipts_no_truncate BEFORE TRUNCATE ON runtime.receipts
    FOR EACH STATEMENT EXECUTE FUNCTION runtime.forbid_evidence_mutation();

CREATE OR REPLACE FUNCTION runtime.forbid_grant_scope_change() RETURNS trigger AS $$
DECLARE
    lifecycle_keys text[] := ARRAY['status', 'commits_used', 'expires_at', 'authorized_at', 'authorized_by', 'grant_digest'];
BEGIN
    IF (OLD.body - lifecycle_keys) IS DISTINCT FROM (NEW.body - lifecycle_keys) THEN
        RAISE EXCEPTION 'task grant % scope is frozen (a body key outside the lifecycle set changed)', OLD.grant_id
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF NEW.max_commits IS DISTINCT FROM OLD.max_commits THEN
        RAISE EXCEPTION 'task grant % max_commits is frozen', OLD.grant_id
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF NEW.commits_used < OLD.commits_used THEN
        RAISE EXCEPTION 'task grant % commit count cannot decrease', OLD.grant_id
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF NEW.status = 'active' AND OLD.status NOT IN ('draft', 'active') THEN
        RAISE EXCEPTION 'task grant % cannot return to active from %', OLD.grant_id, OLD.status
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF NEW.status = 'active' AND OLD.status = 'draft'
       AND (NEW.authorized_by IS NULL OR NEW.authorized_at IS NULL) THEN
        RAISE EXCEPTION 'task grant % cannot become active without an authorizing identity', OLD.grant_id
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS task_grants_scope_frozen ON runtime.task_grants;
CREATE TRIGGER task_grants_scope_frozen BEFORE UPDATE ON runtime.task_grants
    FOR EACH ROW EXECUTE FUNCTION runtime.forbid_grant_scope_change();
