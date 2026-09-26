CREATE TABLE IF NOT EXISTS grokcell_owner_budgets (
    owner_id text PRIMARY KEY,
    available_units bigint NOT NULL CHECK (available_units >= 0),
    reserved_units bigint NOT NULL DEFAULT 0 CHECK (reserved_units >= 0),
    spent_units bigint NOT NULL DEFAULT 0 CHECK (spent_units >= 0)
);

CREATE TABLE IF NOT EXISTS grokcell_cell_heads (
    cell_id text PRIMARY KEY,
    owner_id text NOT NULL,
    revision bigint NOT NULL DEFAULT 0 CHECK (revision >= 0),
    fence bigint NOT NULL DEFAULT 0 CHECK (fence >= 0),
    lease_owner text,
    lease_expires_at timestamptz,
    admitted_state_sha256 text NOT NULL CHECK (admitted_state_sha256 ~ '^[0-9a-f]{64}$'),
    initial_event_index bigint NOT NULL CHECK (initial_event_index >= 0),
    last_event_index bigint NOT NULL CHECK (last_event_index >= initial_event_index),
    initial_checkpoint_key text NOT NULL,
    initial_checkpoint_version text NOT NULL,
    initial_checkpoint_sha256 text NOT NULL CHECK (initial_checkpoint_sha256 ~ '^[0-9a-f]{64}$'),
    initial_manifest_key text NOT NULL,
    initial_manifest_version text NOT NULL,
    initial_manifest_sha256 text NOT NULL CHECK (initial_manifest_sha256 ~ '^[0-9a-f]{64}$'),
    checkpoint_key text NOT NULL,
    checkpoint_version text NOT NULL,
    checkpoint_sha256 text NOT NULL CHECK (checkpoint_sha256 ~ '^[0-9a-f]{64}$'),
    manifest_key text NOT NULL,
    manifest_version text NOT NULL,
    manifest_sha256 text NOT NULL CHECK (manifest_sha256 ~ '^[0-9a-f]{64}$'),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE IF NOT EXISTS grokcell_attempts (
    attempt_id uuid PRIMARY KEY,
    admission_id uuid NOT NULL UNIQUE,
    owner_id text NOT NULL,
    cell_id text NOT NULL REFERENCES grokcell_cell_heads(cell_id),
    idempotency_key text NOT NULL,
    request_sha256 text NOT NULL CHECK (request_sha256 ~ '^[0-9a-f]{64}$'),
    expected_revision bigint NOT NULL CHECK (expected_revision >= 0),
    fence bigint NOT NULL CHECK (fence > 0),
    reserved_units bigint NOT NULL CHECK (reserved_units > 0),
    actual_units bigint,
    status text NOT NULL CHECK (status IN ('dispatch_intent','outcome_unknown','admitted','reconciled_unknown')),
    result_sha256 text CHECK (result_sha256 IS NULL OR result_sha256 ~ '^[0-9a-f]{64}$'),
    result_revision bigint CHECK (result_revision IS NULL OR result_revision >= 0),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE(owner_id, idempotency_key)
);

CREATE UNIQUE INDEX IF NOT EXISTS grokcell_one_open_attempt_per_cell
    ON grokcell_attempts(cell_id)
    WHERE status IN ('dispatch_intent','outcome_unknown');

CREATE TABLE IF NOT EXISTS grokcell_admission_segments (
    cell_id text NOT NULL REFERENCES grokcell_cell_heads(cell_id),
    revision bigint NOT NULL CHECK (revision > 0),
    admission_id uuid NOT NULL UNIQUE REFERENCES grokcell_attempts(admission_id),
    first_event_index bigint NOT NULL CHECK (first_event_index > 0),
    last_event_index bigint NOT NULL CHECK (last_event_index >= first_event_index),
    pre_state_sha256 text NOT NULL CHECK (pre_state_sha256 ~ '^[0-9a-f]{64}$'),
    post_state_sha256 text NOT NULL CHECK (post_state_sha256 ~ '^[0-9a-f]{64}$'),
    checkpoint_key text NOT NULL,
    checkpoint_version text NOT NULL,
    checkpoint_sha256 text NOT NULL CHECK (checkpoint_sha256 ~ '^[0-9a-f]{64}$'),
    event_key text NOT NULL,
    event_version text NOT NULL,
    event_sha256 text NOT NULL CHECK (event_sha256 ~ '^[0-9a-f]{64}$'),
    manifest_key text NOT NULL,
    manifest_version text NOT NULL,
    manifest_sha256 text NOT NULL CHECK (manifest_sha256 ~ '^[0-9a-f]{64}$'),
    previous_manifest_sha256 text NOT NULL CHECK (previous_manifest_sha256 ~ '^[0-9a-f]{64}$'),
    PRIMARY KEY(cell_id, revision)
);

CREATE TABLE IF NOT EXISTS grokcell_outbox (
    event_id text PRIMARY KEY,
    attempt_id uuid NOT NULL UNIQUE REFERENCES grokcell_attempts(attempt_id),
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    published_at timestamptz
);
