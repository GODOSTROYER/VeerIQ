-- RewindSafe schema v1
-- Four schemas with deliberately separated trust:
--   app        synthetic SaaS order-management data (the thing being repaired)
--   authority  PROTECTED current decisions: deletions (tombstones), access grants, holds, epochs
--   recovery   immutable approved snapshots + UNTRUSTED annotations
--   runtime    grants, runs, proposals, decisions, manifests, approvals, receipts, events
-- Historical snapshots never write to authority.*; the recovery executor role has
-- no write privilege on authority.* at all (enforced by PostgreSQL, see roles below).

CREATE SCHEMA IF NOT EXISTS app;
CREATE SCHEMA IF NOT EXISTS authority;
CREATE SCHEMA IF NOT EXISTS recovery;
CREATE SCHEMA IF NOT EXISTS runtime;

-- ─── Fixture generation (reset protocol) ────────────────────────────────────
CREATE TABLE runtime.fixture_state (
    id          smallint PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    generation  bigint NOT NULL,
    reset_at    timestamptz NOT NULL DEFAULT now(),
    reset_by    text NOT NULL DEFAULT 'system'
);

-- ─── app: synthetic application ─────────────────────────────────────────────
CREATE TABLE app.tenants (
    tenant_id  text PRIMARY KEY,
    name       text NOT NULL
);

CREATE TABLE app.customers (
    customer_id  text PRIMARY KEY,
    tenant_id    text NOT NULL REFERENCES app.tenants(tenant_id),
    name         text NOT NULL,
    email        text NOT NULL,
    row_version  bigint NOT NULL DEFAULT 1,
    updated_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE app.orders (
    order_id         text PRIMARY KEY,
    tenant_id        text NOT NULL REFERENCES app.tenants(tenant_id),
    customer_id      text NOT NULL REFERENCES app.customers(customer_id) ON DELETE CASCADE,
    status           text NOT NULL,
    total_cents      bigint NOT NULL CHECK (total_cents >= 0),
    currency         text NOT NULL DEFAULT 'USD',
    shipping_region  text,
    item_summary     text NOT NULL,
    owner_account    text NOT NULL,          -- authority-bearing: ordinary repair may never change it
    row_version      bigint NOT NULL DEFAULT 1,
    updated_at       timestamptz NOT NULL DEFAULT now(),
    updated_by       text NOT NULL
);
CREATE INDEX orders_tenant_idx ON app.orders (tenant_id);

CREATE TABLE app.incidents (
    incident_id   text PRIMARY KEY,
    tenant_ids    text[] NOT NULL,
    title         text NOT NULL,
    description   text NOT NULL,
    started_at    timestamptz NOT NULL,
    detected_at   timestamptz NOT NULL,
    affected      jsonb NOT NULL            -- [{"tenant_id":"atlas","order_id":"O-2041","damage":"..."}]
);

-- ─── authority: protected current decisions ─────────────────────────────────
CREATE TABLE authority.tenant_epochs (
    tenant_id   text PRIMARY KEY REFERENCES app.tenants(tenant_id),
    epoch       bigint NOT NULL DEFAULT 1,   -- bumped by EVERY authority change for the tenant
    updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE authority.tombstones (
    tenant_id    text NOT NULL,
    entity_type  text NOT NULL CHECK (entity_type IN ('customer', 'order')),
    entity_id    text NOT NULL,
    display_name text NOT NULL,
    deleted_at   timestamptz NOT NULL,
    reason       text NOT NULL,
    deleted_by   text NOT NULL,
    PRIMARY KEY (tenant_id, entity_type, entity_id)
);

CREATE TABLE authority.access_grants (
    grant_id        text PRIMARY KEY,
    tenant_id       text NOT NULL REFERENCES app.tenants(tenant_id),
    principal       text NOT NULL,
    scope           text NOT NULL,
    status          text NOT NULL CHECK (status IN ('active', 'revoked')),
    revoked_at      timestamptz,
    revoked_by      text,
    revoked_reason  text,
    row_version     bigint NOT NULL DEFAULT 1,
    updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE authority.record_holds (
    hold_id      text PRIMARY KEY,
    tenant_id    text NOT NULL,
    entity_type  text NOT NULL,
    entity_id    text NOT NULL,
    reason       text NOT NULL,
    placed_by    text NOT NULL,
    placed_at    timestamptz NOT NULL DEFAULT now(),
    active       boolean NOT NULL DEFAULT true
);
CREATE INDEX record_holds_entity_idx ON authority.record_holds (tenant_id, entity_type, entity_id) WHERE active;

-- ─── recovery: immutable snapshots + untrusted annotations ──────────────────
CREATE TABLE recovery.snapshots (
    snapshot_id     text PRIMARY KEY,
    taken_at        timestamptz NOT NULL,
    description     text NOT NULL,
    content         jsonb NOT NULL,           -- {"tenants":[..],"customers":[..],"orders":[..],"access_grants":[..]}
    content_digest  text NOT NULL,            -- sha256 over canonical JSON of content
    approved        boolean NOT NULL DEFAULT false,
    approved_by     text,
    approved_at     timestamptz
);

CREATE TABLE recovery.annotations (
    annotation_id  text PRIMARY KEY,
    snapshot_id    text NOT NULL REFERENCES recovery.snapshots(snapshot_id) ON DELETE CASCADE,
    author         text NOT NULL,
    created_at     timestamptz NOT NULL,
    body           text NOT NULL,
    trust          text NOT NULL DEFAULT 'untrusted' CHECK (trust IN ('untrusted'))
);

-- Snapshots are immutable outside the trusted fixture-reset routine.
CREATE OR REPLACE FUNCTION recovery.forbid_snapshot_mutation() RETURNS trigger AS $$
BEGIN
    IF coalesce(current_setting('rewindsafe.fixture_reset', true), 'off') = 'on' THEN
        RETURN coalesce(NEW, OLD);
    END IF;
    RAISE EXCEPTION 'recovery.snapshots is immutable (attempted % on %)', TG_OP, coalesce(OLD.snapshot_id, NEW.snapshot_id)
        USING ERRCODE = 'insufficient_privilege';
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER snapshots_immutable BEFORE UPDATE OR DELETE ON recovery.snapshots
    FOR EACH ROW EXECUTE FUNCTION recovery.forbid_snapshot_mutation();

-- ─── runtime ────────────────────────────────────────────────────────────────
CREATE TABLE runtime.task_grants (
    grant_id            text PRIMARY KEY,
    workflow            text NOT NULL,
    scenario_id         text NOT NULL,
    principal           text NOT NULL,
    principal_email     text NOT NULL,
    tenant_id           text NOT NULL,
    incident_id         text,
    purpose             text NOT NULL,
    body                jsonb NOT NULL,       -- full TaskGrant JSON (authoritative copy)
    status              text NOT NULL CHECK (status IN ('draft','active','exhausted','expired','revoked')),
    commits_used        int NOT NULL DEFAULT 0,
    max_commits         int NOT NULL,
    created_at          timestamptz NOT NULL DEFAULT now(),
    expires_at          timestamptz NOT NULL,
    authorized_at       timestamptz,
    authorized_by       text,
    fixture_generation  bigint NOT NULL,
    grant_digest        text NOT NULL
);

CREATE TABLE runtime.runs (
    run_id              text PRIMARY KEY,
    grant_id            text NOT NULL REFERENCES runtime.task_grants(grant_id),
    scenario_id         text NOT NULL,
    workflow            text NOT NULL,
    planner             text NOT NULL,
    planner_kind        text NOT NULL,
    enforcement_mode    text NOT NULL CHECK (enforcement_mode IN ('live','offline')),
    status              text NOT NULL,
    outcome_summary     text,
    steps_used          int NOT NULL DEFAULT 0,
    replans_used        int NOT NULL DEFAULT 0,
    plan                jsonb,                -- PlanBinding JSON
    fixture_generation  bigint NOT NULL,
    created_by          text NOT NULL,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    finished_at         timestamptz,
    metadata            jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX runs_created_idx ON runtime.runs (created_at DESC);

CREATE TABLE runtime.proposals (
    proposal_id  text PRIMARY KEY,
    run_id       text NOT NULL REFERENCES runtime.runs(run_id),
    step_index   int NOT NULL,
    tool         text NOT NULL,
    arguments    jsonb NOT NULL,
    rationale    text NOT NULL DEFAULT '',
    source       text NOT NULL,
    status       text NOT NULL DEFAULT 'pending',
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX proposals_run_idx ON runtime.proposals (run_id, step_index);

CREATE TABLE runtime.decisions (
    decision_id  text PRIMARY KEY,
    run_id       text NOT NULL,
    proposal_id  text,
    layer        text NOT NULL,
    source       text NOT NULL,
    outcome      text NOT NULL,
    decisive     boolean NOT NULL DEFAULT false,
    shadow       boolean NOT NULL DEFAULT false,
    simulated    boolean NOT NULL DEFAULT false,
    body         jsonb NOT NULL,              -- full Decision JSON
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX decisions_run_idx ON runtime.decisions (run_id, created_at);

CREATE TABLE runtime.manifests (
    manifest_id         text PRIMARY KEY,
    grant_id            text NOT NULL REFERENCES runtime.task_grants(grant_id),
    run_id              text NOT NULL,
    tenant_id           text NOT NULL,
    body                jsonb NOT NULL,       -- full ExecutionManifest JSON (immutable)
    content_digest      text NOT NULL,
    status              text NOT NULL DEFAULT 'prepared',
    fixture_generation  bigint NOT NULL,
    created_at          timestamptz NOT NULL DEFAULT now()
);

-- Manifest content is immutable; only status may change.
CREATE OR REPLACE FUNCTION runtime.forbid_manifest_content_change() RETURNS trigger AS $$
BEGIN
    IF NEW.body IS DISTINCT FROM OLD.body OR NEW.content_digest IS DISTINCT FROM OLD.content_digest
       OR NEW.grant_id IS DISTINCT FROM OLD.grant_id OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id THEN
        RAISE EXCEPTION 'manifest % content is immutable', OLD.manifest_id USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER manifests_immutable BEFORE UPDATE ON runtime.manifests
    FOR EACH ROW EXECUTE FUNCTION runtime.forbid_manifest_content_change();

CREATE TABLE runtime.approvals (
    approval_id            text PRIMARY KEY,
    run_id                 text NOT NULL,
    grant_id               text NOT NULL,
    proposal_id            text NOT NULL,
    tenant_id              text NOT NULL,
    payload_digest         text NOT NULL,
    status                 text NOT NULL DEFAULT 'pending',
    body                   jsonb NOT NULL,    -- full ApprovalRecord JSON
    requested_at           timestamptz NOT NULL DEFAULT now(),
    expires_at             timestamptz NOT NULL,
    decided_at             timestamptz,
    decided_by             text,
    fixture_generation     bigint NOT NULL
);
CREATE INDEX approvals_status_idx ON runtime.approvals (tenant_id, status);

CREATE TABLE runtime.receipts (
    operation_id        text PRIMARY KEY,
    grant_id            text NOT NULL,
    idempotency_key     text NOT NULL,
    run_id              text NOT NULL,
    manifest_id         text NOT NULL,
    manifest_digest     text NOT NULL,
    result              text NOT NULL,
    body                jsonb NOT NULL,       -- full ExecutionReceipt JSON
    receipt_digest      text NOT NULL,
    fixture_generation  bigint NOT NULL,
    created_at          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (grant_id, idempotency_key)
);

CREATE TABLE runtime.events (
    seq         bigserial PRIMARY KEY,
    run_id      text NOT NULL,
    event_type  text NOT NULL,
    body        jsonb NOT NULL,               -- full RunEvent JSON minus seq
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX events_run_seq_idx ON runtime.events (run_id, seq);

-- Written on a SEPARATE autocommit connection at the very top of every mutator
-- handler, so an entry survives even if the mutation later rolls back. Zero rows
-- for (run_id, handler) proves a prohibited handler was never entered.
CREATE TABLE runtime.mutator_entries (
    entry_id     bigserial PRIMARY KEY,
    run_id       text,
    proposal_id  text,
    handler      text NOT NULL,
    via          text NOT NULL,               -- 'dispatcher' | 'operator_admin' | 'test'
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX mutator_entries_idx ON runtime.mutator_entries (handler, run_id);

-- ArmorIQ report() delivery tracking (telemetry is separate from the durable receipt).
CREATE TABLE runtime.telemetry_outbox (
    outbox_id    bigserial PRIMARY KEY,
    run_id       text NOT NULL,
    proposal_id  text,
    kind         text NOT NULL,               -- 'armoriq.report'
    payload      jsonb NOT NULL,
    status       text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','delivered','failed','skipped')),
    attempts     int NOT NULL DEFAULT 0,
    last_error   text,
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE runtime.verification_runs (
    verification_id  text PRIMARY KEY,
    started_at       timestamptz NOT NULL DEFAULT now(),
    finished_at      timestamptz,
    status           text NOT NULL,           -- 'running' | 'passed' | 'failed' | 'blocked'
    enforcement_mode text NOT NULL,
    results          jsonb NOT NULL DEFAULT '[]'::jsonb,
    summary          jsonb NOT NULL DEFAULT '{}'::jsonb
);

-- ─── Roles: PostgreSQL is the innermost defense layer ──────────────────────
-- rs_executor: the ONLY role used to mutate application data during recovery.
-- Column-level UPDATE on repairable order columns only; read-only on authority.
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rs_executor') THEN
        CREATE ROLE rs_executor NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rs_authority_admin') THEN
        CREATE ROLE rs_authority_admin NOLOGIN;
    END IF;
END $$;

GRANT USAGE ON SCHEMA app, authority, recovery, runtime TO rs_executor, rs_authority_admin;
GRANT SELECT ON ALL TABLES IN SCHEMA app, authority, recovery TO rs_executor, rs_authority_admin;
GRANT UPDATE (status, total_cents, shipping_region, row_version, updated_at, updated_by) ON app.orders TO rs_executor;
GRANT SELECT, INSERT, UPDATE ON runtime.receipts, runtime.task_grants, runtime.manifests, runtime.approvals TO rs_executor;
GRANT SELECT ON ALL TABLES IN SCHEMA runtime TO rs_executor, rs_authority_admin;
GRANT SELECT, UPDATE ON runtime.fixture_state TO rs_authority_admin;
-- authority admin: may change current decisions (operator-only path, never the agent)
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA authority TO rs_authority_admin;
-- The application login role must be a member so it can SET LOCAL ROLE inside transactions.
DO $$ BEGIN
    EXECUTE format('GRANT rs_executor, rs_authority_admin TO %I', current_user);
END $$;
