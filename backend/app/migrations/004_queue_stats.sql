-- /health must see the whole queue, but the API role (hc_app) sees only its own tenant's
-- jobs. queue_stats() runs as the owner and returns two numbers, never a row: no tenant
-- data crosses the boundary. FORCE RLS binds the owner too, so the owner gets a read-only
-- policy that holds only inside this function (it turns app.queue_stats on, then off;
-- the policy is TO hc_owner, so another role setting it gains nothing).
CREATE POLICY queue_stats_owner ON jobs FOR SELECT TO hc_owner
    USING (current_setting('app.queue_stats', true) = 'on');

-- A job is waiting when it is due and unclaimed, or claimed and not finished (a hung
-- worker). waiting_consent and future retries are not waiting on us.
CREATE FUNCTION queue_stats(OUT queued int, OUT oldest_wait_s int)
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = public AS $$
DECLARE
    prev_tenant text := current_setting('app.tenant_id', true);
BEGIN
    -- tenant_isolation raises on an unset tenant (by design); a nil tenant matches no row
    PERFORM set_config('app.tenant_id', '00000000-0000-0000-0000-000000000000', true);
    PERFORM set_config('app.queue_stats', 'on', true);
    SELECT count(*)::int,
           coalesce(extract(epoch FROM max(now() - coalesce(locked_at, run_after))), 0)::int
    INTO queued, oldest_wait_s
    FROM jobs
    WHERE (status = 'queued' AND run_after <= now()) OR status = 'running';
    PERFORM set_config('app.queue_stats', 'off', true);
    PERFORM set_config('app.tenant_id', coalesce(prev_tenant, ''), true);
END
$$;
REVOKE ALL ON FUNCTION queue_stats() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION queue_stats() TO hc_app;
