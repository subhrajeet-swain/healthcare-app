CREATE TABLE tenants (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    slug text UNIQUE NOT NULL,
    name text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE tenant_keys (
    tenant_id uuid PRIMARY KEY REFERENCES tenants(id),
    data_key_enc bytea NOT NULL,
    fp_key_enc bytea NOT NULL
);

CREATE TABLE tenant_settings (
    tenant_id uuid NOT NULL REFERENCES tenants(id),
    version int NOT NULL,
    settings jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, version)
);

CREATE TABLE users (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES tenants(id),
    role text NOT NULL CHECK (role IN ('patient','lab_staff','doctor','lab_admin','platform_admin')),
    phone_fp bytea NOT NULL,
    phone_enc bytea NOT NULL,
    name_enc bytea,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, phone_fp),
    UNIQUE (tenant_id, id)
);

CREATE TABLE otp_codes (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES tenants(id),
    phone_fp bytea NOT NULL,
    code_hash bytea NOT NULL,
    expires_at timestamptz NOT NULL,
    attempts int NOT NULL DEFAULT 0,
    used_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX otp_codes_phone ON otp_codes (tenant_id, phone_fp, created_at);

-- (tenant_id, user_id) foreign keys: rows of two tenants can never be linked.
CREATE TABLE sessions (
    token_hash bytea PRIMARY KEY,
    tenant_id uuid NOT NULL,
    user_id uuid NOT NULL,
    expires_at timestamptz NOT NULL,
    FOREIGN KEY (tenant_id, user_id) REFERENCES users (tenant_id, id) ON DELETE CASCADE
);

CREATE TABLE consents (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    user_id uuid NOT NULL,
    purpose text NOT NULL,
    version text NOT NULL,
    granted_at timestamptz NOT NULL DEFAULT now(),
    withdrawn_at timestamptz,
    FOREIGN KEY (tenant_id, user_id) REFERENCES users (tenant_id, id) ON DELETE CASCADE
);

-- Append-only; monthly partitions come in phase 6, the default partition holds everything now.
CREATE TABLE audit_log (
    id bigint GENERATED ALWAYS AS IDENTITY,
    tenant_id uuid NOT NULL,
    actor_user_id uuid,
    action text NOT NULL,
    entity text NOT NULL,
    entity_id text NOT NULL,
    at timestamptz NOT NULL DEFAULT now()
) PARTITION BY RANGE (at);
CREATE TABLE audit_log_default PARTITION OF audit_log DEFAULT;

CREATE TABLE jobs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES tenants(id),
    kind text NOT NULL,
    payload jsonb NOT NULL DEFAULT '{}',
    status text NOT NULL DEFAULT 'queued',
    run_after timestamptz NOT NULL DEFAULT now(),
    attempts int NOT NULL DEFAULT 0,
    locked_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX jobs_ready ON jobs (status, run_after);
