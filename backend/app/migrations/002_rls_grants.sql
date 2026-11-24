-- Row-level security, forced, on every table that carries tenant_id.
DO $$
DECLARE t text;
BEGIN
    FOR t IN
        SELECT cl.relname FROM pg_class cl
        JOIN pg_namespace n ON n.oid = cl.relnamespace AND n.nspname = 'public'
        JOIN pg_attribute a ON a.attrelid = cl.oid AND a.attname = 'tenant_id'
        WHERE cl.relkind IN ('r', 'p')
    LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
        EXECUTE format(
            'CREATE POLICY tenant_isolation ON %I '
            'USING (tenant_id = current_setting(''app.tenant_id'')::uuid) '
            'WITH CHECK (tenant_id = current_setting(''app.tenant_id'')::uuid)', t);
    END LOOP;
END $$;

GRANT USAGE ON SCHEMA public TO hc_app;
GRANT SELECT ON tenants TO hc_app;
GRANT SELECT, INSERT, UPDATE, DELETE
    ON tenant_keys, tenant_settings, users, otp_codes, sessions, consents, jobs TO hc_app;
GRANT SELECT, INSERT ON audit_log TO hc_app;

CREATE SCHEMA graph AUTHORIZATION hc_graph;
REVOKE ALL ON SCHEMA graph FROM PUBLIC;
