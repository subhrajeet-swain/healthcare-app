# Phase 0: Foundation, implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** a running skeleton (API, web shell, Postgres) where tenant isolation, encryption, OTP login, audit, consent and data rights already work and are proven by tests, before any patient feature exists.

**Architecture:** a FastAPI monolith (sync endpoints, psycopg 3 connection pool) talks to Postgres 16 as a **non-owner role with row-level security forced**. Every data access goes through `tenant_tx(ctx)`, which runs `set_config('app.tenant_id', …, true)` inside one transaction. Migrations are plain SQL files applied by a tiny runner as the owner role. LangGraph's checkpointer lives in its own schema under its own role. The web shell is React with Vite and calls the API through a dev proxy.

**Tech Stack:** Python 3.12, uv, FastAPI, Pydantic v2 + pydantic-settings, psycopg 3 + psycopg_pool, cryptography (Fernet, HMAC), langsmith, langgraph-checkpoint-postgres, pytest, ruff · Node 22, React 18, TypeScript, Vite, Vitest, ESLint · Docker Compose · GitHub Actions.

**Spec:** [phase-0-foundation.md](phase-0-foundation.md), plus [PLAN.md](../PLAN.md) sections 3, 5.3, 5.6 and 6.

## Global Constraints

- Every table with a `tenant_id` column has row-level security **enabled and forced**, plus a policy `USING (tenant_id = current_setting('app.tenant_id')::uuid) WITH CHECK (same)`.
- The app connects as `hc_app` (`NOBYPASSRLS`, not the table owner). Migrations run as `hc_owner`. The checkpointer runs as `hc_graph` in schema `graph`.
- Tenant setting is `SET LOCAL` only (`set_config(…, true)`), inside a transaction. Never a session-level `SET`.
- The tenant comes from the login route's lab slug or the session cookie, never from a request body field.
- "Not found" and "not allowed" return the same status and body.
- Patient-identifying fields (phone, name) are stored only Fernet-encrypted with the tenant's key; phone lookup uses an HMAC-SHA256 fingerprint keyed per tenant.
- `audit_log` is append-only for `hc_app` (no UPDATE or DELETE grant).
- The OTP is fake in dev: printed to the API log, never returned in a response.
- LangSmith masking is on by default; tracing is off unless `LANGSMITH_TRACING=true`.
- Work on branch `phase-0`, cut from `main`; merge to `main` through a PR after Task 11.
- Commits: author `Subhrajeet Swain <subhrajeet.diaz@gmail.com>`, conventional prefixes, **no Co-Authored-By or AI attribution lines**.
- Ponytail: no abstractions with one implementation, no extra dependencies beyond the Tech Stack line.

## Review Focus

1. **A pooled connection reused after another tenant's transaction.** After a `tenant_tx` commits, the same physical connection must not see any rows without a new `tenant_tx`. Postgres returns `''` for a custom setting once it has been defined in a session, and `''::uuid` must still raise. Test in Task 3.
2. **Phone formats.** `98765 43210`, `+91-98765-43210`, `09876543210` and `+919876543210` must give the same fingerprint; `12345` and letters must be rejected with 422. Test in Task 4.
3. **OTP abuse.** A wrong code 5 times locks that code; an expired code fails; a used code cannot be reused; more than 3 OTP requests per phone in 10 minutes gets a 429. Test in Task 5.
4. **A tampered session cookie** (tenant B's id plus tenant A's token, or garbage) gets the same 401 as no cookie. Test in Task 5.
5. **Delete, then log in again.** After delete-my-data, logging in with the same phone creates a fresh patient with no old consents. A second delete with the same (now invalid) cookie is 401, not 500. Test in Task 6.

---

## File structure

```
healthcare-app/
  docker-compose.yml                 db, api, web
  docker/postgres/init/01-roles.sql  roles + database (runs once on an empty volume)
  .env.example
  .github/workflows/ci.yml
  backend/
    pyproject.toml
    Dockerfile
    app/
      main.py         FastAPI app, routers, error handlers, /health
      config.py       Settings (pydantic-settings)
      db.py           pool, tenant_tx, owner_tx
      tenancy.py      TenantCtx, Role
      migrate.py      SQL migration runner + checkpointer setup
      migrations/     001_core.sql, 002_rls_grants.sql
      crypto.py       master key, tenant keys, encrypt/decrypt, phone normalise + fingerprint
      audit.py        audit()
      auth.py         OTP, sessions, current_ctx dependency, /api/auth/*
      privacy.py      /api/me, consents, export, delete
      tracing.py      LangSmith masking
      seed.py         two labs + canary data
    tests/
      conftest.py     fresh hc_test database per session, client fixture
      test_*.py       one file per task
  evals/
    run.py            local runner, optional --langsmith
    datasets/smoke.jsonl
  web/                Vite + React + TS shell
```

---

### Task 1: Repo skeleton, health endpoint, database container, CI

**Files:**
- Create: `docker-compose.yml` (only the `db` service in this task), `docker/postgres/init/01-roles.sql`, `.env.example`, `backend/pyproject.toml`, `backend/app/__init__.py`, `backend/app/config.py`, `backend/app/main.py`, `backend/tests/test_health.py`, `.github/workflows/ci.yml`

**Interfaces:**
- Produces: `app.config.settings: Settings` with fields `database_url`, `owner_database_url`, `graph_database_url`, `admin_database_url`, `master_key`, `otp_pepper`, `env: Literal["dev","test","prod"]`, `langsmith_tracing: bool = False`; `app.main.app: FastAPI`.

- [ ] **Step 1: Write `01-roles.sql`**

```sql
CREATE ROLE hc_owner LOGIN PASSWORD 'owner_dev' CREATEDB;
CREATE ROLE hc_app   LOGIN PASSWORD 'app_dev'   NOBYPASSRLS;
CREATE ROLE hc_graph LOGIN PASSWORD 'graph_dev' NOBYPASSRLS;
CREATE DATABASE healthcare OWNER hc_owner;
```

`db` service: `postgres:16-alpine`, `POSTGRES_PASSWORD=postgres`, host port `5433:5432`, the init folder mounted at `/docker-entrypoint-initdb.d`, a named volume, and a healthcheck with `pg_isready`.

- [ ] **Step 2: `.env.example`** with `DATABASE_URL=postgresql://hc_app:app_dev@localhost:5433/healthcare`, `OWNER_DATABASE_URL` (`hc_owner`), `GRAPH_DATABASE_URL` (`hc_graph`), `ADMIN_DATABASE_URL=postgresql://postgres:postgres@localhost:5433/postgres`, `MASTER_KEY=` (a Fernet key), `OTP_PEPPER=`, `ENV=dev`, `LANGSMITH_TRACING=false`, `LANGSMITH_API_KEY=`, `LANGSMITH_PROJECT=healthcare-app`, plus `WA_PHONE_NUMBER_ID=`, `WA_BUSINESS_ACCOUNT_ID=`, `WA_ACCESS_TOKEN=`. Keep the user's existing `.env` untouched.

- [ ] **Step 3: Write the failing test** `test_health_ok`: `GET /health` returns 200 and `{"status": "ok"}`.

- [ ] **Step 4: Run it to see it fail.** `cd backend && uv run pytest tests/test_health.py -v`. Expected: an import error, because `app.main` doesn't exist yet.

- [ ] **Step 5: Implement `pyproject.toml`, `config.py` and `main.py`**, using `requires-python = ">=3.12"`, the dependencies from the Tech Stack line, ruff (line length 100), and the pytest `testpaths`.

- [ ] **Step 6: Run the test and see it pass.** Also run `uv run ruff check .`, which should be clean.

- [ ] **Step 7: CI workflow** with a `backend` job on Ubuntu: a `postgres:16` service, a step that runs `psql -f docker/postgres/init/01-roles.sql` against the service as `postgres`, `astral-sh/setup-uv`, `uv sync`, `ruff check`, and `pytest`. Secrets come from generated test values set in the workflow env, never from repo secrets.

- [ ] **Step 8: `docker compose up -d db`** and check that `docker compose ps` shows `db` as healthy.

- [ ] **Step 9: Commit**: `chore: repo skeleton, health endpoint, postgres roles, CI`.

---

### Task 2: Migration runner, core schema, row-level security and grants

**Files:**
- Create: `backend/app/migrate.py`, `backend/app/migrations/001_core.sql`, `backend/app/migrations/002_rls_grants.sql`, `backend/tests/conftest.py`, `backend/tests/test_schema.py`

**Interfaces:**
- Produces: `migrate.run(owner_url: str) -> list[str]`, which applies the not-yet-applied `migrations/*.sql` files in name order, each in its own transaction, records them in `schema_migrations(name text primary key, applied_at timestamptz)`, and returns the names it applied. It is also a CLI: `python -m app.migrate`.
- Produces tables (001), all with `tenant_id uuid not null` except `tenants` and `schema_migrations`:
  - `tenants(id uuid pk default gen_random_uuid(), slug text unique not null, name text not null, created_at)`
  - `tenant_keys(tenant_id pk fk, data_key_enc bytea, fp_key_enc bytea)`
  - `tenant_settings(tenant_id, version int, settings jsonb, created_at, pk(tenant_id, version))`
  - `users(id uuid pk, tenant_id, role text check in ('patient','lab_staff','doctor','lab_admin','platform_admin'), phone_fp bytea not null, phone_enc bytea not null, name_enc bytea, created_at, unique(tenant_id, phone_fp))`
  - `otp_codes(id uuid pk, tenant_id, phone_fp bytea, code_hash bytea, expires_at, attempts int default 0, used_at)`
  - `sessions(token_hash bytea pk, tenant_id, user_id fk on delete cascade, expires_at)`
  - `consents(id uuid pk, tenant_id, user_id fk on delete cascade, purpose text, version text, granted_at, withdrawn_at)`
  - `audit_log(id bigint generated always as identity, tenant_id, actor_user_id uuid, action text, entity text, entity_id text, at timestamptz default now()) PARTITION BY RANGE (at)`, plus `audit_log_default PARTITION OF audit_log DEFAULT`
  - `jobs(id uuid pk, tenant_id, kind text, payload jsonb, status text default 'queued', run_after timestamptz default now(), attempts int default 0, locked_at timestamptz, created_at)` with index `(status, run_after)`
- Produces (002): row-level security enabled and forced plus the `tenant_isolation` policy on every tenant table (including `audit_log` and its default partition). `GRANT USAGE ON SCHEMA public` and `SELECT, INSERT, UPDATE, DELETE` on tenant tables to `hc_app`; on `audit_log`, **only `SELECT, INSERT`**; `SELECT` on `tenants` to `hc_app`. `CREATE SCHEMA graph AUTHORIZATION hc_graph; REVOKE ALL ON SCHEMA graph FROM PUBLIC`.
- Produces fixtures (`conftest.py`): a session-scoped `db_urls` fixture that drops and recreates database `hc_test` (owner `hc_owner`) through `ADMIN_DATABASE_URL`, runs `migrate.run`, and yields the URLs pointing at `hc_test`.

- [ ] **Step 1: Write the failing tests** in `test_schema.py`:
  - `test_migrate_is_idempotent`: a second `migrate.run` returns `[]`.
  - `test_every_tenant_table_has_forced_rls_and_policy`: query `pg_class` joined to `pg_attribute`, where column = `tenant_id` and the relation kind is `r` or `p`. For each one, assert `relrowsecurity` and `relforcerowsecurity` are true and `pg_policies` has at least one row.
  - `test_app_role_cannot_bypass_rls`: `SELECT rolbypassrls FROM pg_roles WHERE rolname='hc_app'` is false.
  - `test_audit_log_is_append_only_for_app`: as `hc_app`, `UPDATE audit_log …` and `DELETE FROM audit_log` raise `psycopg.errors.InsufficientPrivilege`.
  - `test_app_role_has_no_access_to_graph_schema`: as `hc_app`, `CREATE TABLE graph.x()` raises `InsufficientPrivilege`.

- [ ] **Step 2: Run and see them fail.** `uv run pytest tests/test_schema.py -v`.
- [ ] **Step 3: Implement** `migrate.py`, `001_core.sql` and `002_rls_grants.sql`.
- [ ] **Step 4: Run and see them pass.**
- [ ] **Step 5: Commit**: `feat: core schema with forced row-level security and grants`.

---

### Task 3: Tenant context and the tenant transaction (TDD)

**Files:**
- Create: `backend/app/tenancy.py`, `backend/app/db.py`, `backend/tests/test_tenancy.py`

**Interfaces:**
- Produces: `Role = Literal["patient","lab_staff","doctor","lab_admin","platform_admin"]`; `@dataclass(frozen=True) TenantCtx(tenant_id: UUID, user_id: UUID | None = None, role: Role | None = None)`.
- Produces: `db.init_pool(url: str) -> None`; `db.tenant_tx(ctx: TenantCtx) -> ContextManager[psycopg.Connection]`, which takes a pooled connection, opens a transaction, runs `SELECT set_config('app.tenant_id', %s, true)`, yields the connection and commits (or rolls back on an exception); `db.owner_tx(url: str, tenant_id: UUID | None = None) -> ContextManager[Connection]`, for provisioning, seed and tests, setting the tenant the same way when given. Rows come back as dicts (`row_factory=dict_row`).

- [ ] **Step 1: Write the failing tests** (two tenants inserted through `owner_tx`, each with one `users` row):
  - `test_tenant_sees_only_own_rows`: `SELECT count(*) FROM users` inside `tenant_tx(ctx_a)` equals 1, and the row's `tenant_id` equals A.
  - `test_query_without_tenant_raises`: a raw pooled connection running `SELECT * FROM users` raises a `psycopg.Error`.
  - `test_reused_connection_after_tenant_tx_raises` (**Review Focus 1**): use a pool of `min_size=max_size=1`; run `tenant_tx(ctx_a)`, then on the same pool, outside any `tenant_tx`, `SELECT * FROM users` raises.
  - `test_insert_for_other_tenant_rejected`: inside `tenant_tx(ctx_a)`, inserting a `users` row with `tenant_id=B` raises `psycopg.errors.InsufficientPrivilege` (the WITH CHECK violation).
  - `test_other_tenant_id_lookup_returns_nothing`: inside `tenant_tx(ctx_a)`, `SELECT … WHERE id = <B's user id>` returns `None`.

- [ ] **Step 2: Run and see them fail.**
- [ ] **Step 3: Implement** `tenancy.py` and `db.py`.
- [ ] **Step 4: Run and see them pass.**
- [ ] **Step 5: Commit**: `feat: TenantCtx and tenant_tx with SET LOCAL tenant`.

---

### Task 4: Per-tenant encryption and the phone fingerprint (TDD)

**Files:**
- Create: `backend/app/crypto.py`, `backend/tests/test_crypto.py`

**Interfaces:**
- Consumes: `owner_tx`, `tenant_tx`, `TenantCtx`.
- Produces:
  - `normalise_phone(raw: str) -> str`: returns E.164. Strip spaces, dashes and brackets; a leading `0` with 10 digits after it, or bare 10 digits, becomes `+91…`; `+91` with 10 digits is kept; anything else raises `ValueError("invalid_phone")`.
  - `provision_tenant(slug: str, name: str) -> UUID`: through `owner_tx`, inserts `tenants` and `tenant_keys`, with a fresh Fernet data key and a 32-byte fingerprint key, both encrypted with `Fernet(settings.master_key)`.
  - `class TenantCipher` with `encrypt(text: str) -> bytes`, `decrypt(token: bytes) -> str`, `fingerprint(phone_e164: str) -> bytes` (HMAC-SHA256 with the tenant's fingerprint key).
  - `cipher_for(conn: Connection, tenant_id: UUID) -> TenantCipher`: reads `tenant_keys` in the current transaction and caches per process in a module-level dict. `# ponytail: per-process key cache, no eviction; fine for 20 tenants`.

- [ ] **Step 1: Write the failing tests:**
  - `test_phone_formats_normalise_equal` (**Review Focus 2**): `"98765 43210"`, `"+91-98765-43210"`, `"09876543210"` and `"+919876543210"` all give `"+919876543210"`.
  - `test_invalid_phone_rejected`: `"12345"`, `"abcdefghij"` and `""` raise `ValueError`.
  - `test_encrypt_roundtrip_and_not_plaintext`: `decrypt(encrypt("Ramesh"))` is `"Ramesh"`, and `b"Ramesh"` does not appear in the ciphertext.
  - `test_same_phone_different_tenants_different_fingerprint`.
  - `test_other_tenant_cannot_decrypt`: tenant B's cipher on tenant A's ciphertext raises `cryptography.fernet.InvalidToken`.
  - `test_tenant_keys_not_stored_in_plaintext`: the raw `data_key_enc` differs from the key the cipher uses.

- [ ] **Step 2: Run and see them fail.**
- [ ] **Step 3: Implement** `crypto.py`.
- [ ] **Step 4: Run and see them pass.**
- [ ] **Step 5: Commit**: `feat: per-tenant Fernet encryption and keyed phone fingerprint`.

---

### Task 5: OTP login, sessions, the current-context dependency and the audit write (TDD)

**Files:**
- Create: `backend/app/audit.py`, `backend/app/auth.py`, `backend/tests/test_auth.py`
- Modify: `backend/app/main.py` (include the router; add the error handler so `NotFound` gives `404 {"error":"not_found"}`; init the pool on startup)

**Interfaces:**
- Consumes: `tenant_tx`, `TenantCtx`, `cipher_for`, `normalise_phone`.
- Produces:
  - `audit(conn: Connection, ctx: TenantCtx, action: str, entity: str, entity_id: str) -> None`: one insert, in the caller's transaction.
  - `POST /api/auth/{slug}/otp` with body `{"phone": str}`. Always `202 {"status":"sent"}` for a valid phone (no hint whether the user exists). 422 for an invalid phone, 404 for an unknown slug, and 429 when there are already 3 requests for that phone fingerprint in the last 10 minutes. It stores `code_hash = HMAC-SHA256(otp_pepper, code)`, with `expires_at = now + 5 min`. In dev it logs `OTP for +91******3210: 123456`.
  - `POST /api/auth/{slug}/verify` with body `{"phone": str, "code": str}`. On success, a user is created with role `patient` if the fingerprint is new, the code is marked used, a session is created (32 random bytes, `sha256` stored, 7-day expiry), and an HTTP-only cookie `hc_session=<tenant_id>.<token>` is set (`SameSite=Lax`, `Secure` when `env=="prod"`). The response is `{"role": …}`. Failures are `401 {"error":"invalid_code"}`. Each wrong try increments `attempts`; at 5 or more, the code is dead.
  - `POST /api/auth/logout`: deletes the session and clears the cookie, then 204.
  - `current_ctx(request) -> TenantCtx`, a FastAPI dependency: it parses the cookie, looks up `sha256(token)` inside `tenant_tx(TenantCtx(tenant_id))`, and checks expiry. **Any** failure (missing, malformed, wrong tenant, expired) gives the same `401 {"error":"unauthenticated"}`.

- [ ] **Step 1: Write the failing tests** (the OTP is captured from the log with `caplog`):
  - `test_login_happy_path_sets_cookie_and_creates_patient`.
  - `test_otp_not_in_response_body`.
  - `test_unknown_and_known_phone_same_otp_response`.
  - `test_wrong_code_five_times_locks` (**Review Focus 3**): after 5 wrong tries, the right code gives 401.
  - `test_expired_code_rejected`: set `expires_at` in the past through `owner_tx`, then expect 401.
  - `test_used_code_rejected`.
  - `test_fourth_otp_request_in_10_min_is_429`.
  - `test_tampered_cookie_same_401` (**Review Focus 4**): no cookie, garbage, `<tenantB>.<tokenA>` and an expired session all give identical status and body.
  - `test_login_writes_audit_row`: the audit action is `"login"`.

- [ ] **Step 2: Run and see them fail.**
- [ ] **Step 3: Implement** `audit.py` and `auth.py`.
- [ ] **Step 4: Run and see them pass.**
- [ ] **Step 5: Commit**: `feat: phone OTP login, sessions and audit writes`.

---

### Task 6: Me, consent, export and delete-my-data

**Files:**
- Create: `backend/app/privacy.py`, `backend/tests/test_privacy.py`
- Modify: `backend/app/main.py` (include the router)

**Interfaces:**
- Consumes: `current_ctx`, `tenant_tx`, `cipher_for`, `audit`.
- Produces:
  - `GET /api/me` returns `{"id", "role", "phone_masked": "+91******3210", "name": str | null, "consent": {"core": bool}}`, and audits `("read","user",id)`.
  - `POST /api/consents` with body `{"purpose": "core", "version": "2026-11-v1"}` returns 201. `purpose` must be one of `{"core"}` for now (422 otherwise).
  - `DELETE /api/consents/{purpose}` sets `withdrawn_at`, then 204.
  - `GET /api/me/export` returns JSON `{"user": {...decrypted}, "consents": [...]}` with `Content-Disposition: attachment; filename=my-data.json`, and audits `("export","user",id)`.
  - `DELETE /api/me` deletes the user (sessions and consents cascade), audits `("delete","user",id)` **before** the delete in the same transaction, clears the cookie, then 204. `# ponytail: row delete only; per-user key shredding (backups) comes with real users`.

- [ ] **Step 1: Write the failing tests:**
  - `test_me_requires_login`: 401.
  - `test_me_masks_phone_and_audits_read`.
  - `test_consent_grant_and_withdraw_reflected_in_me`.
  - `test_unknown_consent_purpose_422`.
  - `test_export_contains_decrypted_data_and_audits`.
  - `test_delete_removes_rows_and_session`: after the delete, `users`, `sessions` and `consents` for that id are 0 (counted through `owner_tx` with the tenant set), and the audit row with `action="delete"` remains.
  - `test_relogin_after_delete_is_fresh_account` (**Review Focus 5**): a new user id and `consent.core` is false.
  - `test_second_delete_with_old_cookie_is_401` (**Review Focus 5**).

- [ ] **Step 2: Run and see them fail.**
- [ ] **Step 3: Implement** `privacy.py`.
- [ ] **Step 4: Run and see them pass.**
- [ ] **Step 5: Commit**: `feat: me, consent, export and delete-my-data endpoints`.

---

### Task 7: LangGraph checkpointer in its own schema and role

**Files:**
- Modify: `backend/app/migrate.py` (after the SQL files, call `setup_checkpointer(graph_url)`)
- Create: `backend/tests/test_checkpointer.py`

**Interfaces:**
- Produces: `migrate.setup_checkpointer(graph_url: str) -> None`. It connects as `hc_graph` with `options="-c search_path=graph"` and `autocommit=True`, then calls `PostgresSaver(conn).setup()`. It is idempotent (the library tracks its own migrations).

- [ ] **Step 1: Write the failing tests:**
  - `test_checkpoint_tables_in_graph_schema_owned_by_hc_graph`: `pg_tables` where `schemaname='graph'` includes `checkpoints`, with `tableowner='hc_graph'`.
  - `test_app_role_cannot_read_checkpoints`: as `hc_app`, `SELECT * FROM graph.checkpoints` raises `InsufficientPrivilege`.
- [ ] **Step 2: Run and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run and see them pass**, and check that the whole suite is still green.
- [ ] **Step 5: Commit**: `feat: LangGraph checkpointer in isolated graph schema`.

---

### Task 8: LangSmith masking and the eval runner skeleton

**Files:**
- Create: `backend/app/tracing.py`, `backend/tests/test_tracing.py`, `evals/run.py`, `evals/datasets/smoke.jsonl`

**Interfaces:**
- Produces:
  - `tracing.mask(data: Any) -> Any`: recursive. Values under the keys `{"phone","name","patient_name","dob","email","address"}` become `"[REDACTED]"`; in every string, Indian mobile numbers (`(\+91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}`) and emails become `[PHONE]` / `[EMAIL]`.
  - `tracing.client() -> langsmith.Client`: `Client(hide_inputs=mask, hide_outputs=mask)`. Later phases pass it to tracing. Nothing is sent unless `LANGSMITH_TRACING=true`.
  - `evals/run.py`: `python evals/run.py <dataset> [--langsmith]`. It reads JSONL rows `{"input": …, "expected": …}`, runs the target `TARGETS[dataset]` (a dict of dataset name to callable), scores with exact match, prints `passed/total`, and exits 1 if any case fails. With `--langsmith` it uploads the dataset (if missing) and runs `langsmith.evaluate` with the same target and scorer. Smoke target: `lambda x: x` with 2 rows.

- [ ] **Step 1: Write the failing tests:**
  - `test_mask_redacts_pii_keys_nested`: `{"patient": {"name": "Ramesh Kumar", "phone": "+919876543210"}}`, where neither value survives anywhere in `json.dumps(mask(...))`.
  - `test_mask_scrubs_phone_and_email_in_free_text`: `"call 98765 43210 or a@b.com"` contains neither.
  - `test_client_uses_mask`: `tracing.client()._hide_inputs is tracing.mask`. If the attribute name differs in the installed langsmith version, assert through its public behaviour instead, and write down which.
- [ ] **Step 2: Run and see them fail.**
- [ ] **Step 3: Implement** `tracing.py`, `run.py` and the smoke dataset.
- [ ] **Step 4: Run and see them pass**; `uv run python ../evals/run.py smoke` prints `2/2` and exits 0.
- [ ] **Step 5: Add an eval step to CI** (local mode only).
- [ ] **Step 6: Commit**: `feat: LangSmith PII masking and eval runner skeleton`.

---

### Task 9: Seed data and canary isolation tests

**Files:**
- Create: `backend/app/seed.py`, `backend/tests/test_canary.py`
- Modify: `.github/workflows/ci.yml` (the canary test already runs in pytest; no change unless it's split out)

**Interfaces:**
- Consumes: `provision_tenant`, `owner_tx`, `cipher_for`.
- Produces: `seed.run() -> dict[str, UUID]`, idempotent (it skips if the slugs exist). It creates labs `lab-alpha` and `lab-beta`, each with one `lab_admin`, one `doctor`, one `lab_staff` and two patients. Canary patient names are `CANARY-ALPHA-7319` and `CANARY-BETA-4826`. **Phone `+919000000001` is a patient in both labs** (two separate users). It is also a CLI: `python -m app.seed`.

- [ ] **Step 1: Write the failing tests:**
  - `test_shared_phone_two_tenants_two_users`: each tenant's `tenant_tx` finds exactly one user for that phone's fingerprint, and the ids differ.
  - `test_canary_never_crosses`: for each tenant, decrypt every `name_enc` visible in its `tenant_tx`; `CANARY-BETA` never appears for alpha, and the other way round.
  - `test_login_as_alpha_cannot_reach_beta_user`: log in as the shared phone at `lab-alpha`, then `GET /api/me` returns alpha's user id, never beta's.
  - `test_every_api_route_rejects_cross_tenant_cookie`: for every route in `app.routes` under `/api/` except the auth routes, a request with `<beta_tenant>.<alpha_token>` gets 401.
- [ ] **Step 2: Run and see them fail.**
- [ ] **Step 3: Implement** `seed.py`.
- [ ] **Step 4: Run and see them pass.**
- [ ] **Step 5: Commit**: `feat: two-lab seed with canaries and isolation tests`.

---

### Task 10: Web shell (login, consent, role dashboards, design tokens)

Use the **`impeccable`** skill for the design direction and tokens before writing components.

**Files:**
- Create: `web/` (scaffold with `npm create vite@latest web -- --template react-ts`), `web/src/api.ts`, `web/src/routes.tsx`, `web/src/pages/Login.tsx`, `web/src/pages/Consent.tsx`, `web/src/pages/Dashboard.tsx`, `web/src/styles/tokens.css`, `web/src/routes.test.ts`
- Modify: `web/vite.config.ts` (proxy `/api` to `http://localhost:8000`; Vitest config)

**Interfaces:**
- Consumes: `/api/auth/{slug}/otp`, `/api/auth/{slug}/verify`, `/api/auth/logout`, `/api/me`, `/api/consents`, `/api/me/export`, `DELETE /api/me`.
- Produces: routes `/:slug/login`, `/consent`, `/` (dashboard). `dashboardFor(role: Role): string` returns the heading text: patient "Your reports", lab_staff "Lab console", doctor "Review queue", lab_admin "Lab settings", platform_admin "Platform".

- [ ] **Step 1: Run `impeccable`** to pick the direction (calm, clinical, readable for older users; Hindi-ready type) and write `tokens.css` (colour, type scale, spacing, radius, focus ring, plus red, amber and green triage tokens with text labels, never colour alone).
- [ ] **Step 2: Write the failing test** `routes.test.ts`: `dashboardFor` maps all 5 roles exactly as above.
- [ ] **Step 3: Run `npm test`** and see it fail.
- [ ] **Step 4: Implement** `api.ts` (fetch with `credentials: "include"`, throws on non-2xx with the `error` field), the pages and the routes. Login flow: phone, then OTP, then `/consent` if `consent.core` is false, else `/`. The dashboard shows an empty state per role, plus "Download my data", "Delete my data" (confirm dialog) and "Log out".
- [ ] **Step 5: Run `npm test`, `npm run lint` and `npm run build`**; all must pass.
- [ ] **Step 6: Add a `web` job to CI**: `npm ci`, lint, test, build.
- [ ] **Step 7: Commit**: `feat: web shell with login, consent and role dashboards`.

---

### Task 11: Full Docker Compose stack, done-when check, reviews

**Files:**
- Create: `backend/Dockerfile` (`python:3.12-slim`, uv, `CMD` runs `python -m app.migrate && uvicorn app.main:app --host 0.0.0.0 --port 8000`)
- Modify: `docker-compose.yml` (add `api`, which depends on db being healthy and uses `env_file: .env` with the database host `db`; and `web` as `node:22-alpine` running `npm ci && npm run dev -- --host`, with the proxy target set from env to `http://api:8000`)

- [ ] **Step 1: `docker compose up --build`**, then `docker compose exec api python -m app.seed`.
- [ ] **Step 2: Manual check** against the phase 0 "Done when" list. At `http://localhost:5173/lab-alpha/login`, log in as `+919000000001`, with the OTP from `docker compose logs api`. Expect the consent screen, then the "Your reports" dashboard, then export downloads JSON, then delete logs you out.
- [ ] **Step 3: Run the full suites**: `uv run pytest -q`, `npm test`, `python evals/run.py smoke`. All green. Push and confirm CI is green.
- [ ] **Step 4: Run `code-review`** on the phase 0 branch and fix the findings.
- [ ] **Step 5: Run `security-review`** and fix the findings. Phase 0 is not done while any tenant-leak, auth or secret finding is open.
- [ ] **Step 6: Tick the "Done when" boxes** in `phase-0-foundation.md` and commit: `chore: phase 0 complete`.
