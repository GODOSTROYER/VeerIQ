-- Generic imported repair values are stored apart from immutable record
-- identity/tenant columns. The catalog defines the permitted JSONB keys/types.
ALTER TABLE app.import_inventory_items
    ADD COLUMN IF NOT EXISTS repair_values jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE recovery.import_datasets
    ADD COLUMN IF NOT EXISTS repairable_types jsonb NOT NULL DEFAULT '{}'::jsonb;

CREATE TABLE IF NOT EXISTS recovery.import_dataset_fields (
    dataset_id text NOT NULL REFERENCES recovery.import_datasets(dataset_id) ON DELETE CASCADE,
    field_name text NOT NULL CHECK (field_name ~ '^[A-Za-z_][A-Za-z0-9_]{0,63}$'),
    source_column text NOT NULL CHECK (source_column ~ '^[A-Za-z_][A-Za-z0-9_]{0,63}$'),
    scalar_type text NOT NULL CHECK (scalar_type IN ('string', 'integer', 'number', 'boolean')),
    PRIMARY KEY (dataset_id, field_name),
    UNIQUE (dataset_id, source_column)
);

-- Backfill datasets created by the previous import adapter. Its only writable
-- fields were quantity and location, and those are still present as legacy
-- mirror columns for existing reads.
INSERT INTO recovery.import_dataset_fields(dataset_id, field_name, source_column, scalar_type)
SELECT d.dataset_id, v.field_name, d.mapping->>v.field_name, v.scalar_type
FROM recovery.import_datasets d
CROSS JOIN (VALUES ('quantity', 'integer'), ('location', 'string')) AS v(field_name, scalar_type)
WHERE d.mapping ? v.field_name
ON CONFLICT (dataset_id, field_name) DO NOTHING;

UPDATE recovery.import_datasets d
SET repairable_types = coalesce((
    SELECT jsonb_object_agg(f.field_name, f.scalar_type)
    FROM recovery.import_dataset_fields f WHERE f.dataset_id = d.dataset_id
), '{}'::jsonb)
WHERE d.repairable_types = '{}'::jsonb;

UPDATE recovery.import_datasets d
SET current_rows = coalesce((
    SELECT jsonb_agg(x.value || jsonb_build_object('repair_values', coalesce((
        SELECT jsonb_object_agg(f.field_name, x.value->f.field_name)
        FROM recovery.import_dataset_fields f WHERE f.dataset_id=d.dataset_id
    ), '{}'::jsonb)))
    FROM jsonb_array_elements(d.current_rows) AS x(value)
), '[]'::jsonb);

-- The prior schema made imported snapshots immutable. This migration is the
-- only compatibility rewrite, and runs in the fixture-reset maintenance mode.
SET LOCAL rewindsafe.fixture_reset = 'on';
UPDATE recovery.import_snapshots s
SET content = jsonb_set(s.content, '{rows}', coalesce((
    SELECT jsonb_agg(x.value || jsonb_build_object('repair_values', coalesce((
        SELECT jsonb_object_agg(f.field_name, x.value->f.field_name)
        FROM recovery.import_dataset_fields f WHERE f.dataset_id=d.dataset_id
    ), '{}'::jsonb)))
    FROM jsonb_array_elements(s.content->'rows') AS x(value)
), '[]'::jsonb))
FROM recovery.import_datasets d WHERE d.snapshot_id=s.snapshot_id;
SET LOCAL rewindsafe.fixture_reset = 'off';

UPDATE app.import_inventory_items i
SET repair_values =
    (CASE WHEN EXISTS (
        SELECT 1 FROM recovery.import_dataset_fields f
        WHERE f.dataset_id=i.dataset_id AND f.field_name='quantity'
    ) THEN jsonb_build_object('quantity', i.quantity) ELSE '{}'::jsonb END)
    ||
    (CASE WHEN EXISTS (
        SELECT 1 FROM recovery.import_dataset_fields f
        WHERE f.dataset_id=i.dataset_id AND f.field_name='location'
    ) THEN jsonb_build_object('location', i.location) ELSE '{}'::jsonb END)
WHERE repair_values = '{}'::jsonb;

-- Preserve the old inventory columns as a compatibility mirror for legacy
-- consumers. The executor still receives UPDATE on repair_values only; this
-- trigger does not expand its column privileges.
CREATE OR REPLACE FUNCTION recovery.sync_import_legacy_repair_mirrors() RETURNS trigger AS $$
BEGIN
    IF NEW.repair_values ? 'quantity'
       AND jsonb_typeof(NEW.repair_values->'quantity') = 'number'
       AND (NEW.repair_values->>'quantity') ~ '^-?[0-9]+$' THEN
        NEW.quantity := (NEW.repair_values->>'quantity')::bigint;
    END IF;
    IF NEW.repair_values ? 'location'
       AND jsonb_typeof(NEW.repair_values->'location') IN ('string', 'null') THEN
        NEW.location := CASE WHEN jsonb_typeof(NEW.repair_values->'location')='null'
                             THEN NULL ELSE NEW.repair_values->>'location' END;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS import_repair_mirror_sync ON app.import_inventory_items;
CREATE TRIGGER import_repair_mirror_sync
    BEFORE UPDATE OF repair_values ON app.import_inventory_items
    FOR EACH ROW EXECUTE FUNCTION recovery.sync_import_legacy_repair_mirrors();

REVOKE UPDATE (quantity, location) ON app.import_inventory_items FROM rs_import_executor;
GRANT UPDATE (repair_values, row_version, updated_at, updated_by)
    ON app.import_inventory_items TO rs_import_executor;
