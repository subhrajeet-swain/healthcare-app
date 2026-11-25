# Phase 0: Foundation

Status: done (2026-11-25). Depends on: nothing. See [PLAN.md](../PLAN.md) for the shared rules.

## 1. Plan

**Goal:** a skeleton that every later phase builds on, with the hard-to-retrofit parts done first: tenant isolation, audit and consent. There are no patient features yet.

**In scope**
- Repo layout (`backend/`, `web/`, `evals/`, `docker-compose.yml`) and one command to start everything.
- Postgres with migrations, and **row-level security forced on every tenant table**. A missing `app.tenant_id` is an error, never "all rows".
- `TenantCtx`: worked out once per request from the login and required by every database function.
- Phone OTP login. The OTP is fake in dev (printed to the log), because real Indian SMS needs DLT registration.
- Roles: `patient`, `lab_staff`, `doctor`, `lab_admin`, `platform_admin`. Session in an HTTP-only cookie.
- Per-tenant encryption key (Fernet) for patient-identifying fields; keyed phone fingerprint per tenant.
- `audit_log`, append-only: every read and write of patient data, recording who, what, when and which tenant.
- Consent screen and consent record (purpose and version); data export (JSON) and delete-my-data.
- Seed script: 2 test labs with canary patients (unique fake names and value patterns).
- CI: lint (ruff, eslint), tests, and the canary isolation tests on every push.
- An eval-harness skeleton (`evals/`) that later phases add cases to, built on **LangSmith datasets and experiments**, with a local pytest runner so CI works without the network.
- A LangSmith project, with tracing turned on through environment variables and **input and output masking on by default**. One test proves that a trace contains no phone number or name.
- LangGraph's Postgres checkpointer tables created by a migration, owned by a separate database role (PLAN 5.6).
- An empty web shell: login page, an empty dashboard for each role, and a design-token foundation built with `impeccable`.

**Out of scope:** reports, chat, any model call, WhatsApp, voice.

**Design notes**
- Migrations: plain SQL files plus a tiny runner, or Alembic. Pick the smaller one at the start (ponytail).
- Every database function takes `ctx: TenantCtx` as its first argument, and each transaction runs `SET LOCAL app.tenant_id`. Use the SQL from the voice doc, section 6.
- A test asserts that no tenant table lacks a row-level security policy, so a new table cannot quietly skip it.
- "Not found" and "not allowed" return the same response.

**Done when**
- [x] `docker compose up` starts the API, the web app and Postgres, and you can log in with the dev OTP.
- [x] A canary test: tenant A, calling every endpoint with tenant B's ids, always gets "not found".
- [x] A query without `app.tenant_id` fails.
- [x] Every patient-data read appears in `audit_log`.
- [x] Export, then delete: the user's rows are gone and their encrypted fields can no longer be read.
- [x] CI is green.
- [x] `security-review` is clean.

**Risks**
- Row-level security plus a connection pool: `SET` leaks between requests. Use `SET LOCAL` only, inside a transaction.
- Over-building auth. Phone OTP plus roles is enough; no OAuth providers.

## 2. Stack and costs

| Need | Choice | Cost |
|---|---|---|
| API | FastAPI, Pydantic v2, psycopg 3 | free |
| Database | Postgres 16 in Docker | free |
| Encryption | `cryptography` (Fernet); keys in env or file for dev | free |
| Web | React, TypeScript, Vite | free |
| CI | GitHub Actions (private repo minutes) | free tier; verify current minutes |
| Tracing and evals | LangSmith Developer plan | free tier; check the monthly trace limit |
| LangGraph checkpointer | `langgraph-checkpoint-postgres` | free |
| OTP | fake in dev; real SMS provider (MSG91 or similar plus DLT) only when going live | ₹0 now |

## 3. Coding

Milestones. They are expanded into step-by-step tasks with `superpowers:writing-plans` when the phase starts.

1. Repo skeleton, Docker Compose, a health endpoint, CI.
2. Schema: `tenants`, `tenant_settings`, `users`, `consents`, `audit_log`, `jobs`. Row-level security on all of them, plus the "every table has a policy" test.
3. `TenantCtx`, the session and the transaction helper with `SET LOCAL`. **TDD.**
4. OTP login and roles.
5. Encryption per tenant and the phone fingerprint. **TDD.**
6. The audit-log write path and the consent, export and delete endpoints.
7. Seed data and canary tests in CI.
8. The web shell: login, role dashboards, design tokens (`impeccable`).

## 4. Skills this phase
`superpowers:writing-plans`, `superpowers:test-driven-development` (tenant context, encryption), `ponytail`, `impeccable` (shell and tokens), `code-review`, `security-review`.
