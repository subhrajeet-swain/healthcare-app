-- Phase 1: report vault, status steps, chat.
CREATE TABLE reports (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    user_id uuid NOT NULL,
    uploaded_by uuid NOT NULL,
    source text NOT NULL CHECK (source IN ('patient','lab')),
    status text NOT NULL CHECK (status IN ('sample_collected','in_lab','received','extracting',
        'explaining','needs_review','ready','failed')),
    file_mime text,
    file_sha256 bytea,
    triage text CHECK (triage IN ('red','amber','green')),
    next_step text,
    urgent boolean NOT NULL DEFAULT false,
    collected_on date,
    failure_message text,
    warnings jsonb NOT NULL DEFAULT '[]',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, id),
    FOREIGN KEY (tenant_id, user_id) REFERENCES users (tenant_id, id) ON DELETE CASCADE
);
CREATE INDEX reports_user ON reports (tenant_id, user_id, created_at DESC);

CREATE TABLE results (
    tenant_id uuid NOT NULL,
    report_id uuid NOT NULL,
    test_id text NOT NULL,
    test_name text NOT NULL,
    value double precision NOT NULL,
    unit text NOT NULL,
    ref_low double precision,
    ref_high double precision,
    printed_flag text,
    flag text NOT NULL CHECK (flag IN ('low','normal','high','critical')),
    triage text NOT NULL CHECK (triage IN ('red','amber','green')),
    PRIMARY KEY (report_id, test_id),
    FOREIGN KEY (tenant_id, report_id) REFERENCES reports (tenant_id, id) ON DELETE CASCADE
);

CREATE TABLE explanations (
    tenant_id uuid NOT NULL,
    report_id uuid NOT NULL,
    language text NOT NULL,
    source text NOT NULL CHECK (source IN ('model','template')),
    statements jsonb NOT NULL,
    PRIMARY KEY (report_id, language),
    FOREIGN KEY (tenant_id, report_id) REFERENCES reports (tenant_id, id) ON DELETE CASCADE
);

CREATE TABLE report_steps (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id uuid NOT NULL,
    report_id uuid NOT NULL,
    status text NOT NULL,
    at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (tenant_id, report_id) REFERENCES reports (tenant_id, id) ON DELETE CASCADE
);
CREATE INDEX report_steps_report ON report_steps (report_id, id);

-- Payload carries the report id and status only: no tenant or patient data on the channel.
CREATE FUNCTION notify_report_status() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    PERFORM pg_notify('report_status', NEW.report_id::text || ':' || NEW.status);
    RETURN NEW;
END $$;
CREATE TRIGGER report_steps_notify AFTER INSERT ON report_steps
    FOR EACH ROW EXECUTE FUNCTION notify_report_status();

CREATE TABLE chat_messages (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    report_id uuid NOT NULL,
    user_id uuid NOT NULL,
    role text NOT NULL CHECK (role IN ('user','assistant')),
    text_enc bytea NOT NULL,
    tier text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (tenant_id, report_id) REFERENCES reports (tenant_id, id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id, user_id) REFERENCES users (tenant_id, id) ON DELETE CASCADE
);
CREATE INDEX chat_messages_report ON chat_messages (report_id, created_at);

-- Same loop as 002: forced RLS + tenant_isolation on every tenant table that lacks a policy.
DO $$
DECLARE t text;
BEGIN
    FOR t IN
        SELECT cl.relname FROM pg_class cl
        JOIN pg_namespace n ON n.oid = cl.relnamespace AND n.nspname = 'public'
        JOIN pg_attribute a ON a.attrelid = cl.oid AND a.attname = 'tenant_id'
        WHERE cl.relkind IN ('r', 'p')
          AND NOT EXISTS (SELECT 1 FROM pg_policies p
                          WHERE p.schemaname = 'public' AND p.tablename = cl.relname)
    LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
        EXECUTE format(
            'CREATE POLICY tenant_isolation ON %I '
            'USING (tenant_id = current_setting(''app.tenant_id'')::uuid) '
            'WITH CHECK (tenant_id = current_setting(''app.tenant_id'')::uuid)', t);
    END LOOP;
END $$;

GRANT SELECT, INSERT, UPDATE, DELETE ON reports, results, explanations, chat_messages TO hc_app;
GRANT SELECT, INSERT ON report_steps TO hc_app;

-- The worker (member of hc_app) may see every tenant's jobs, and nothing else across tenants.
CREATE POLICY worker_claim ON jobs FOR ALL TO hc_worker USING (true) WITH CHECK (true);
