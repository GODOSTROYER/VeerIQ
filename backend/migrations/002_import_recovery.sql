-- Generic inventory recovery tables. Snapshot values are immutable and current
-- rows are writable only through the column-limited rs_import_executor role.
CREATE TABLE IF NOT EXISTS recovery.import_snapshots (
    snapshot_id text PRIMARY KEY,
    sample_id text NOT NULL,
    tenant_id text NOT NULL,
    content jsonb NOT NULL,
    content_digest text NOT NULL,
    approved boolean NOT NULL DEFAULT false,
    approved_by text,
    approved_at timestamptz
);

CREATE TABLE IF NOT EXISTS recovery.import_datasets (
    dataset_id text PRIMARY KEY,
    display_name text NOT NULL,
    tenant_id text NOT NULL,
    snapshot_id text NOT NULL REFERENCES recovery.import_snapshots(snapshot_id),
    snapshot_digest text NOT NULL,
    mapping jsonb NOT NULL,
    current_rows jsonb NOT NULL,
    authority_records jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS app.import_inventory_items (
    dataset_id text NOT NULL REFERENCES recovery.import_datasets(dataset_id),
    record_id text NOT NULL,
    tenant_id text NOT NULL,
    sku text NOT NULL,
    description text NOT NULL DEFAULT '',
    quantity bigint NOT NULL,
    location text,
    owner_account text NOT NULL,
    sync_grant_id text,
    row_version bigint NOT NULL DEFAULT 1,
    updated_at timestamptz NOT NULL DEFAULT now(),
    updated_by text NOT NULL,
    PRIMARY KEY (dataset_id, record_id)
);
CREATE INDEX IF NOT EXISTS import_inventory_tenant_idx ON app.import_inventory_items (dataset_id, tenant_id);
CREATE TABLE IF NOT EXISTS authority.import_record_holds (
    dataset_id text NOT NULL,
    record_id text NOT NULL,
    reason text NOT NULL,
    active boolean NOT NULL DEFAULT true,
    placed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (dataset_id, record_id)
);

CREATE TABLE IF NOT EXISTS recovery.import_authority_state (
    dataset_id text NOT NULL REFERENCES recovery.import_datasets(dataset_id),
    record_id text NOT NULL,
    tenant_id text NOT NULL,
    tombstoned boolean NOT NULL,
    revoked boolean NOT NULL,
    held boolean NOT NULL,
    later_edit boolean NOT NULL,
    detail jsonb NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (dataset_id, record_id)
);

ALTER TABLE authority.tombstones DROP CONSTRAINT IF EXISTS tombstones_entity_type_check;
ALTER TABLE authority.tombstones ADD CONSTRAINT tombstones_entity_type_check
    CHECK (entity_type IN ('customer', 'order', 'inventory_item'));

CREATE OR REPLACE FUNCTION recovery.forbid_import_snapshot_mutation() RETURNS trigger AS $$
BEGIN
    IF coalesce(current_setting('rewindsafe.fixture_reset', true), 'off') = 'on' THEN
        RETURN coalesce(NEW, OLD);
    END IF;
    RAISE EXCEPTION 'recovery.import_snapshots is immutable (attempted % on %)', TG_OP,
        coalesce(OLD.snapshot_id, NEW.snapshot_id) USING ERRCODE = 'insufficient_privilege';
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS import_snapshots_immutable ON recovery.import_snapshots;
CREATE TRIGGER import_snapshots_immutable BEFORE UPDATE OR DELETE ON recovery.import_snapshots
    FOR EACH ROW EXECUTE FUNCTION recovery.forbid_import_snapshot_mutation();

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rs_import_executor') THEN
        CREATE ROLE rs_import_executor NOLOGIN;
    END IF;
END $$;
GRANT USAGE ON SCHEMA app, authority, recovery, runtime TO rs_import_executor;
GRANT SELECT ON ALL TABLES IN SCHEMA app, authority, recovery, runtime TO rs_import_executor;
GRANT UPDATE (quantity, location, row_version, updated_at, updated_by)
    ON app.import_inventory_items TO rs_import_executor;
GRANT SELECT, INSERT ON runtime.receipts TO rs_import_executor;
GRANT SELECT, UPDATE (commits_used, status) ON runtime.task_grants TO rs_import_executor;
GRANT SELECT, UPDATE (status) ON runtime.manifests TO rs_import_executor;
DO $$ BEGIN
    EXECUTE format('GRANT rs_import_executor TO %I', current_user);
END $$;
