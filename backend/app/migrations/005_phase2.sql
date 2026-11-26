-- Phase 2: canonical results, trends, the doctor review queue, family links, share links.

-- ADD FOREIGN KEY on an existing table checks its rows through the forced RLS policies, which
-- raise on an unset tenant. A nil tenant matches no row (as in 004); the new columns hold no
-- data yet, so there is nothing for the check to miss. Reverts at the end of the transaction.
SELECT set_config('app.tenant_id', '00000000-0000-0000-0000-000000000000', true);

-- A dependant (a child) has no phone; staff always do. (tenant_id, phone_fp) stays unique
-- among the rows that have one (NULLs are distinct).
ALTER TABLE users
    ALTER COLUMN phone_fp DROP NOT NULL,
    ALTER COLUMN phone_enc DROP NOT NULL,
    ADD CONSTRAINT users_staff_have_phone CHECK (phone_fp IS NOT NULL OR role = 'patient');

-- Who gave the consent when it is not the patient (a manager for a child).
ALTER TABLE consents
    ADD COLUMN granted_by uuid,
    ADD FOREIGN KEY (tenant_id, granted_by) REFERENCES users (tenant_id, id)
        ON DELETE SET NULL (granted_by);

-- The printed value stays the authority; *_c is our converted claim beside it. user_id and
-- observed_on are copied from the report so the timeline is one indexed read.
ALTER TABLE results
    ADD COLUMN user_id uuid NOT NULL,
    ADD COLUMN observed_on date NOT NULL,
    ADD COLUMN value_c double precision,
    ADD COLUMN ref_low_c double precision,
    ADD COLUMN ref_high_c double precision,
    ADD COLUMN unit_c text,
    ADD COLUMN excluded_reason text,
    ADD FOREIGN KEY (tenant_id, user_id) REFERENCES users (tenant_id, id) ON DELETE CASCADE;
CREATE INDEX results_timeline ON results (tenant_id, user_id, test_id, observed_on);

-- review_items points at chat messages by a composite key.
ALTER TABLE chat_messages ADD UNIQUE (tenant_id, id);

CREATE TABLE trends (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    user_id uuid NOT NULL,
    test_id text NOT NULL,
    direction text NOT NULL CHECK (direction IN ('rising','falling')),
    toward text NOT NULL CHECK (toward IN ('out_of_range','critical')),
    first_value double precision NOT NULL,
    last_value double precision NOT NULL,
    unit_c text NOT NULL,
    points int NOT NULL,
    last_report_id uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (user_id, test_id, last_report_id),
    UNIQUE (tenant_id, id),
    FOREIGN KEY (tenant_id, user_id) REFERENCES users (tenant_id, id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id, last_report_id) REFERENCES reports (tenant_id, id) ON DELETE CASCADE
);

CREATE TABLE review_items (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    kind text NOT NULL CHECK (kind IN ('report','trend','chat')),
    reason text NOT NULL CHECK (reason IN ('red','warnings','trend','gated_answer')),
    user_id uuid NOT NULL,
    report_id uuid,
    trend_id uuid,
    chat_message_id uuid,
    thread_id text,
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending','approved','edited','escalated')),
    note_option text,
    decided_by uuid,
    decided_at timestamptz,
    due_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (trend_id),
    UNIQUE (chat_message_id),
    FOREIGN KEY (tenant_id, user_id) REFERENCES users (tenant_id, id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id, report_id) REFERENCES reports (tenant_id, id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id, trend_id) REFERENCES trends (tenant_id, id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id, chat_message_id) REFERENCES chat_messages (tenant_id, id)
        ON DELETE CASCADE,
    -- a doctor who deletes their account leaves the decision standing, unattributed
    FOREIGN KEY (tenant_id, decided_by) REFERENCES users (tenant_id, id)
        ON DELETE SET NULL (decided_by)
);
CREATE UNIQUE INDEX review_one_pending_report ON review_items (report_id)
    WHERE kind = 'report' AND status = 'pending';

CREATE TABLE family_links (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    manager_id uuid NOT NULL,
    member_id uuid NOT NULL,
    relation text NOT NULL CHECK (relation IN ('child','parent','spouse','other')),
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','active','revoked')),
    created_at timestamptz NOT NULL DEFAULT now(),
    accepted_at timestamptz,
    UNIQUE (tenant_id, manager_id, member_id),
    CHECK (manager_id <> member_id),
    FOREIGN KEY (tenant_id, manager_id) REFERENCES users (tenant_id, id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id, member_id) REFERENCES users (tenant_id, id) ON DELETE CASCADE
);

CREATE TABLE share_links (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    user_id uuid NOT NULL,
    created_by uuid NOT NULL,
    token_hash bytea UNIQUE NOT NULL,
    report_ids uuid[] NOT NULL,
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (tenant_id, user_id) REFERENCES users (tenant_id, id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id, created_by) REFERENCES users (tenant_id, id) ON DELETE CASCADE
);

-- Same loop as 003: forced RLS + tenant_isolation on every tenant table that lacks a policy.
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

GRANT SELECT, INSERT, UPDATE, DELETE ON trends, review_items, family_links, share_links TO hc_app;
