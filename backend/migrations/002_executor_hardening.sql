-- 002: tighten the rs_executor role (defense in depth below the application code).
--   * no write access to approvals; receipts are INSERT-only
--   * task_grants / manifests: column-level UPDATE of only what a commit legitimately changes
--   * app.orders: row-level security so rs_executor can only UPDATE rows of the tenant named in
--     the transaction-local setting rewindsafe.tenant (set by the executor before SET LOCAL ROLE).
-- The owner / login role is not subject to RLS (FORCE is not set), so fixture reset is unaffected.

REVOKE INSERT, UPDATE, DELETE ON runtime.approvals FROM rs_executor;
REVOKE UPDATE, DELETE ON runtime.receipts FROM rs_executor;
REVOKE UPDATE, DELETE ON runtime.task_grants FROM rs_executor;
REVOKE UPDATE, DELETE ON runtime.manifests FROM rs_executor;
REVOKE INSERT, DELETE ON runtime.task_grants FROM rs_executor;
REVOKE INSERT, DELETE ON runtime.manifests FROM rs_executor;
GRANT UPDATE (commits_used, status, body) ON runtime.task_grants TO rs_executor;
GRANT UPDATE (status) ON runtime.manifests TO rs_executor;

ALTER TABLE app.orders ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS rs_exec_read ON app.orders;
DROP POLICY IF EXISTS rs_exec_update_tenant ON app.orders;
DROP POLICY IF EXISTS rs_admin_read ON app.orders;
CREATE POLICY rs_exec_read ON app.orders FOR SELECT TO rs_executor USING (true);
CREATE POLICY rs_exec_update_tenant ON app.orders FOR UPDATE TO rs_executor
    USING (tenant_id = current_setting('rewindsafe.tenant', true))
    WITH CHECK (tenant_id = current_setting('rewindsafe.tenant', true));
CREATE POLICY rs_admin_read ON app.orders FOR SELECT TO rs_authority_admin USING (true);
