CREATE TABLE IF NOT EXISTS runtime.auth_sessions (
    session_hash text PRIMARY KEY,
    subject text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL
);

CREATE INDEX IF NOT EXISTS auth_sessions_expires_at_idx ON runtime.auth_sessions (expires_at);

CREATE TABLE IF NOT EXISTS runtime.oidc_login_states (
    state_hash text PRIMARY KEY,
    nonce text NOT NULL,
    code_verifier text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL
);

CREATE INDEX IF NOT EXISTS oidc_login_states_expires_at_idx ON runtime.oidc_login_states (expires_at);
