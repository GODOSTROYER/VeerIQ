-- Preserve operator-provided source fields separately from the repairable
-- JSONB container. rs_import_executor must never be able to edit this data.
ALTER TABLE app.import_inventory_items
    ADD COLUMN IF NOT EXISTS source_metadata jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE recovery.import_datasets
    ADD COLUMN IF NOT EXISTS authority_mapping jsonb NOT NULL DEFAULT
        '{"tombstoned":"tombstoned","revoked":"revoked","held":"held","later_edit":"later_edit"}'::jsonb;

ALTER TABLE recovery.import_dataset_fields
    DROP CONSTRAINT IF EXISTS import_dataset_fields_source_column_check;
ALTER TABLE recovery.import_dataset_fields
    ADD CONSTRAINT import_dataset_fields_source_column_check
    CHECK (octet_length(source_column) BETWEEN 1 AND 512
       AND source_column = btrim(source_column)
       AND source_column !~ '[[:cntrl:]]');

REVOKE UPDATE (source_metadata) ON app.import_inventory_items FROM rs_import_executor;
GRANT UPDATE (repair_values, row_version, updated_at, updated_by)
    ON app.import_inventory_items TO rs_import_executor;
