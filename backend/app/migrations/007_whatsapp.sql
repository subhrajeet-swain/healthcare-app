-- Phase 3: the WhatsApp channel. One business number per lab, a link between a patient and a
-- WhatsApp number, one-time link codes, and the inbound message dedupe table.

-- The ALTERs on reports and chat_messages check their rows through the forced RLS policies,
-- which raise on an unset tenant. A nil tenant matches no row (as in 005); the new check only
-- widens the old one and the new column has a default, so there is nothing for it to miss.
-- Reverts at the end of the transaction.
SELECT set_config('app.tenant_id', '00000000-0000-0000-0000-000000000000', true);

-- tenants is the public directory (no RLS, no tenant_id): the webhook finds the lab by number.
ALTER TABLE tenants
    ADD COLUMN wa_phone_number_id text UNIQUE,
    ADD COLUMN wa_display_phone text;

-- The number is stored as a fingerprint (lookup) and encrypted (to send), as for users.
CREATE TABLE wa_links (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    user_id uuid NOT NULL,
    wa_fp bytea NOT NULL,
    wa_enc bytea NOT NULL,
    lang text NOT NULL DEFAULT 'en' CHECK (lang IN ('en','hi')),
    last_inbound_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, user_id),
    UNIQUE (tenant_id, wa_fp),
    FOREIGN KEY (tenant_id, user_id) REFERENCES users (tenant_id, id) ON DELETE CASCADE
);

CREATE TABLE wa_link_codes (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    user_id uuid NOT NULL,
    code_hash bytea NOT NULL,
    lang text NOT NULL DEFAULT 'en' CHECK (lang IN ('en','hi')),
    expires_at timestamptz NOT NULL,
    used_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (tenant_id, user_id) REFERENCES users (tenant_id, id) ON DELETE CASCADE
);
CREATE INDEX wa_link_codes_hash ON wa_link_codes (tenant_id, code_hash);

-- Meta retries a webhook: message_id is the dedupe key. The sender may be nobody we know, so
-- there is no user to reference. body_enc is cleared once the message is handled.
CREATE TABLE wa_inbound (
    message_id text PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES tenants(id),
    sender_fp bytea NOT NULL,
    body_enc bytea,
    received_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX wa_inbound_sender ON wa_inbound (tenant_id, sender_fp, received_at);

-- 003 declared the check inline, so Postgres named it reports_source_check.
ALTER TABLE reports DROP CONSTRAINT reports_source_check;
ALTER TABLE reports
    ADD CONSTRAINT reports_source_check CHECK (source IN ('patient','lab','whatsapp'));

ALTER TABLE chat_messages
    ADD COLUMN channel text NOT NULL DEFAULT 'web' CHECK (channel IN ('web','whatsapp'));

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

GRANT SELECT, INSERT, UPDATE, DELETE ON wa_links, wa_link_codes, wa_inbound TO hc_app;
