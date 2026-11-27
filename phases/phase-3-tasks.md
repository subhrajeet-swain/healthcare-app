# Phase 3: WhatsApp channel — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** a linked patient sends a report, reads its explanation, chats about it and gets alerts on WhatsApp, with the same brain and the same `chat_messages` as the web app.

**Architecture:** `app/whatsapp.py` is the thin adapter: pure `parse`, `verify_signature`, `split`, the copy and templates, and `send`/`fetch_media` over the Graph API (log-only when no access token). `app/wa_api.py` holds the public webhook (signature check, dedupe on the message id, one `wa.inbound` job per message, 200 fast) and the patient's link routes. `app/wa_jobs.py` holds the two worker handlers: `wa.inbound` (commands, media into the phase 1 pipeline, questions through the shared chat core) and `wa.notify` (report ready, trend alert, review complete). The API never calls Meta; only the worker does.

**Tech Stack:** unchanged (FastAPI, psycopg 3, Postgres 16 RLS, LangGraph, React 19 + Vite). `httpx` moves from the dev group to main dependencies (already in `uv.lock` through langchain; no new package).

**Spec:** [phase-3-whatsapp.md](phase-3-whatsapp.md), with [PLAN.md](../PLAN.md). Phase 2 plan for conventions: [phase-2-tasks.md](phase-2-tasks.md).

## Before starting (user actions)

1. Nothing for tests: every test uses a fake Graph API, no Meta keys.
2. For a real Meta test number later (not in this plan): set `WA_APP_SECRET`, `WA_VERIFY_TOKEN`, `WA_ACCESS_TOKEN` in `.env`, set the lab's `tenants.wa_phone_number_id`, expose `/api/whatsapp/webhook` through cloudflared, and submit the four templates in Task 2's `TEMPLATES` for approval.

## Rulings made while planning

| # | Decision | Why | Cost if wrong |
|---|---|---|---|
| W1 | **Red or held reports never show values or chat on WhatsApp.** Any path that would (REPORT, a question, an in-window notify) sends `COPY["red"]`: "open the app or call your lab". The date-of-birth check (spec R1) moves to phase 4 with voice. *Confirmed by the user 2026-11-26.* | `users` has no DOB; voice needs the same check | red-result patients must use the app |
| W2 | One business number per lab: `tenants.wa_phone_number_id` (unique) and `tenants.wa_display_phone`. The webhook takes the tenant from `metadata.phone_number_id`, never from message text. An unknown number is ignored (200, logged) | `tenants` is already the public directory (no RLS); a shared number plus lab choice is YAGNI | a second number per lab needs a table |
| W3 | Linking: a signed-in patient gets a 6-digit code (10 min, HMAC with `otp_pepper` as `auth._code_hash`, unique among the tenant's live codes) and sends `LINK 123456` from WhatsApp. That proves both the number and the account, and counts as opt-in (consent purpose `whatsapp`). Re-linking replaces: one number per user, one user per number, per tenant | Spec allows a link code; no SMS provider exists | none |
| W4 | An unlinked sender gets at most `UNLINKED_MAX_PER_HOUR = 10` messages handled per hour (counted from `wa_inbound`); the rest are dropped silently | Caps code guessing at 10 per number per hour | a determined attacker with many numbers: ponytail, see Task 5 |
| W5 | Commands (trimmed, case-insensitive, English only): `LINK <6 digits>`, `STOP`, `START`, `REPORT`. Any other text from a linked sender is a question about their latest chat-ready report | Small fixed set; Hindi command words later | none |
| W6 | `STOP` withdraws `whatsapp` consent and sends one confirmation. `START` re-grants it. Every send re-checks the consent at send time; with it withdrawn only the STOP confirmation is ever sent | Spec: opt-out stops all outbound | none |
| W7 | The webhook stores each message encrypted in `wa_inbound (message_id PK)` with `ON CONFLICT DO NOTHING` and queues `wa.inbound {"message_id"}` only on insert. The worker clears `body_enc` after handling; the row stays for dedupe | No PHI in `jobs`; Meta retries; minimal retention | `wa_inbound` grows by one small row per message (purge job later) |
| W8 | 24-hour window from `wa_links.last_inbound_at`. Inside: free text. Outside: a template. Templates carry no result value and no placeholder except `{lab}` | Meta rules; spec: values never in a template | none |
| W9 | `wa.notify {"user_id", "event", "report_id"?}` is queued only when the user has a link. Events: `report_ready` (from `_save`), `review_complete` (from `_review_job`), `trend_alert` (new trend in `store_result`). A report still held at send time sends nothing; its release queues `review_complete` | One handler decides at send time with fresh state | none |
| W10 | The worker treats a job as a report pipeline job by `kind == "report.pipeline"`, not by `"report_id" in payload` (`run_once` thread cleanup, `_sweep_dead`) | A `wa.notify` carrying a `report_id` would otherwise delete a parked review thread | none |
| W11 | Web and WhatsApp share one chat core, `chat_api.converse(...)`; the transaction factory is a parameter (`db.tenant_tx` in the API, the worker role in jobs). `chat_messages.channel` is `web` or `whatsapp`; the per-hour limit counts both channels | One history (spec), one gate, one review path | none |
| W12 | Replies use `wa_links.lang` (`en`/`hi`), set from the app language when the code was requested | No language command needed | none |
| W13 | Media: `GET {wa_graph_url}/{media_id}` gives `url`, `mime_type`, `file_size`; the download is refused unless the URL is `https://lookaside.fbsbx.com/...`, `file_size <= files.MAX_BYTES`, and then the same `files.check_bytes` as web upload. Source `whatsapp` | SSRF guard; one validation path | Meta changes its media host: one constant |

## Global Constraints

- Everything in phase 1 and 2 Global Constraints still holds (tenant tables with RLS forced and composite FKs, `ApiError`, same 404 for missing and forbidden, audit on every patient read, no network in tests, the model never decides anything clinical, no AI attribution in commits, commit as `subhrajeet.diaz@gmail.com`).
- No real Meta keys anywhere. Tests monkeypatch `whatsapp.graph_get_json`, `whatsapp.graph_get_bytes` and `whatsapp.graph_post`; with `settings.wa_access_token` empty, `send` only logs (text only when `env != "prod"`).
- Job kinds added (exact): `wa.inbound`, `wa.notify`. Payloads carry ids only.
- Consent purposes (exact): `core`, `whatsapp`. Consent version for WhatsApp opt-in: `wa-2026-11-v1`.
- Report sources (exact): `patient`, `lab`, `whatsapp`. Chat channels (exact): `web`, `whatsapp`.
- Message chunks are at most `CHUNK = 700` characters.
- Hindi copy is machine-drafted; mark it with the same comment as `Consent.tsx`.
- Run `docker compose stop worker` before the backend suite (the compose worker breaks job-driven tests).
- After every web edit: `docker compose restart web` from the repo root.

## Review Focus

1. **A red or held report leaks on WhatsApp** through REPORT, a question, an in-window notify or a template. Expected: only `COPY["red"]`, no value. Tests: Task 5 `test_report_command_red_sends_red_line`, Task 6 `test_question_on_red_report_refused`, Task 7 `test_notify_held_sends_nothing` and `test_notify_released_red_has_no_values`, Task 9 eval `whatsapp`.
2. **Forged or replayed webhook.** Expected: bad or missing signature 401, no secret configured 503, a duplicate delivery makes one job, an unknown business number makes none. Tests: Task 3.
3. **STOP, then an alert already queued.** Expected: nothing sent. Test: Task 7 `test_notify_after_stop_sends_nothing`.
4. **Someone else's WhatsApp gets linked** (guessed, expired, reused or colliding code). Expected: no link; the 11th message an hour from an unlinked number is dropped. Tests: Task 4 `test_code_unique_among_live_codes`, Task 5 `test_link_expired_or_used_code_rejected`, `test_unlinked_sender_capped`.
5. **A `wa.notify` job for a parked warnings report** deletes the review thread. Expected: the thread survives and the doctor's resume works. Test: Task 7 `test_notify_job_keeps_parked_thread`.

---

### Task 1: Schema, settings, consent purpose

**Files:**
- Create: `backend/app/migrations/007_whatsapp.sql`
- Modify: `backend/app/config.py`, `backend/app/privacy.py`, `backend/app/seed.py`, `backend/pyproject.toml` (+ `uv lock`)
- Test: `backend/tests/test_schema.py`, `backend/tests/test_privacy.py`

**Interfaces:**
- Produces: tables and columns below; `settings.wa_app_secret`, `wa_verify_token`, `wa_access_token` (all `""`), `wa_graph_url = "https://graph.facebook.com/v21.0"`; `privacy.Purpose = Literal["core", "whatsapp"]`; `/api/me` `consent` gains `"whatsapp": bool`; seed sets lab-alpha `wa_phone_number_id = "dev-alpha"`, `wa_display_phone = "+15550000001"` (idempotent).

Migration 007 (set the nil tenant first, as 005 does):
- `tenants`: `wa_phone_number_id text UNIQUE`, `wa_display_phone text`.
- `wa_links (id uuid PK, tenant_id, user_id, wa_fp bytea NOT NULL, wa_enc bytea NOT NULL, lang text NOT NULL DEFAULT 'en' CHECK (lang IN ('en','hi')), last_inbound_at timestamptz, created_at; UNIQUE (tenant_id, user_id), UNIQUE (tenant_id, wa_fp), FK (tenant_id, user_id) → users ON DELETE CASCADE)`.
- `wa_link_codes (id uuid PK, tenant_id, user_id, code_hash bytea NOT NULL, lang text NOT NULL DEFAULT 'en' CHECK (lang IN ('en','hi')), expires_at, used_at, created_at; FK users ON DELETE CASCADE)`, index `(tenant_id, code_hash)`.
- `wa_inbound (message_id text PK, tenant_id NOT NULL REFERENCES tenants, sender_fp bytea NOT NULL, body_enc bytea, received_at timestamptz NOT NULL DEFAULT now())`, index `(tenant_id, sender_fp, received_at)`.
- `reports.source` CHECK becomes `('patient','lab','whatsapp')` (drop `reports_source_check`, add again).
- `chat_messages.channel text NOT NULL DEFAULT 'web' CHECK (channel IN ('web','whatsapp'))`.
- The forced-RLS loop from 005; `GRANT SELECT, INSERT, UPDATE, DELETE ON wa_links, wa_link_codes, wa_inbound TO hc_app`.

- [ ] **Step 1: Failing tests**

```python
# test_schema.py
def test_phase3_tables_have_forced_rls(db_urls): ...  # wa_links, wa_link_codes, wa_inbound, as test_phase2_tables_have_forced_rls

def test_report_source_whatsapp_allowed(db_urls): ...  # insert a report with source 'whatsapp' as owner: ok; 'sms': CheckViolation

def test_chat_channel_defaults_web(db_urls): ...       # insert without channel -> 'web'; 'sms' -> CheckViolation

# test_privacy.py
def test_whatsapp_consent_grant_and_withdraw(client, patient):
    assert client.post("/api/consents", json={"purpose": "whatsapp", "version": "wa-2026-11-v1"}).status_code == 201
    assert client.get("/api/me").json()["consent"] == {"core": True, "whatsapp": True}
    assert client.delete("/api/consents/whatsapp").status_code == 204
    assert client.get("/api/me").json()["consent"]["whatsapp"] is False

def test_whatsapp_grant_does_not_requeue_consent_jobs(client, patient, db_urls): ...
    # a waiting_consent job stays waiting_consent after granting 'whatsapp'
```

- [ ] **Step 2:** Run `uv run pytest tests/test_schema.py tests/test_privacy.py -q`. Expected: FAIL (no tables, 422 on purpose).
- [ ] **Step 3:** Write the migration; add the settings; extend `Purpose` and `me()`; guard the `waiting_consent` re-queue in `grant_consent` with `if body.purpose == "core"`; seed the dev number with `UPDATE tenants SET ... WHERE id = %s AND wa_phone_number_id IS NULL`; move `httpx>=0.27` to `dependencies` and run `uv lock`.
- [ ] **Step 4:** Run the same tests, then the full suite. Expected: PASS. `uv run python -m app.migrate` against dev applies 007.
- [ ] **Step 5:** Commit `feat: whatsapp schema, settings and consent purpose`.

---

### Task 2: The adapter (pure parts, send, media) — TDD

**Files:**
- Create: `backend/app/whatsapp.py`
- Modify: `backend/app/files.py` (add `check_bytes`), `backend/app/reports.py` (`read_upload` calls it)
- Test: `backend/tests/test_whatsapp.py`, `backend/tests/test_reports_api.py` (existing upload tests stay green)

**Interfaces:**
- Produces:
  - `files.check_bytes(data: bytes) -> str`: size (`413 file_too_large`), `sniff`, `check_pdf` for PDFs, `scan`; returns the mime. `read_upload` becomes read + `check_bytes`.
  - `@dataclass(frozen=True) Inbound(message_id: str, phone_number_id: str, sender: str, kind: Literal["text", "media", "other"], text: str | None = None, media_id: str | None = None)`; `sender` is E.164 via `normalise_phone("+" + from)`.
  - `parse(payload: dict) -> list[Inbound]`: every `entry[].changes[].value.messages[]`; `text` → kind text (`text.body`), `document`/`image` → kind media (`id`), anything else → other; `statuses` ignored; a sender `normalise_phone` rejects is skipped; a malformed shape returns what parsed so far, never raises.
  - `verify_signature(body: bytes, header: str | None, secret: str) -> bool`: `header == "sha256=" + hex(HMAC-SHA256(secret, body))` with `hmac.compare_digest`; False for None or empty secret.
  - `split(paragraphs: list[str], limit: int = CHUNK) -> list[str]`: packs paragraphs joined by `"\n\n"` into chunks `<= limit`; a paragraph longer than `limit` is cut at the last space before it.
  - `COPY: dict[str, dict[str, str]]` (keys `linked`, `link_from_app`, `bad_code`, `stopped`, `started`, `consent_needed`, `no_report`, `reading`, `bad_file`, `red`, `not_ready`, `too_many`, `ask_more`) and `TEMPLATES: dict[str, dict[str, str]]` (keys `report_ready`, `trend_alert`, `review_complete`, `report_ready_red`), EN + HI. Exact EN copy for the safety lines: `red` = "Your report needs a doctor's attention. Please open the app or call your lab.", `report_ready_red` = "Your report from {lab} is ready and needs a doctor's attention. Please open the app or call your lab." Other wording is the implementer's: plain, factual, no medical claims, no numbers.
  - `report_paragraphs(detail: dict, lang: str) -> list[str]`: from a patient-view `reports.report_detail`: the explanation statement texts in `lang` (fallback `en`), then `doctor_note.text[lang]` if any, then `nextstep.closing_message(next_step, lang)` if any. Never called for red or held (callers check; it raises `ValueError` if `detail["triage"] == "red"` or `status == "under_review"`).
  - `@dataclass(frozen=True) Outbound(phone_number_id: str, to: str, text: str | None = None, template: str | None = None, lang: str = "en", lab: str = "")`.
  - `send(o: Outbound) -> None`: no token → `log.info` (text only when `env != "prod"`) and return; else `graph_post(f"/{o.phone_number_id}/messages", body)` with a text body, or a template body (name, `language.code` `en`/`hi`, one body parameter `lab`).
  - `fetch_media(media_id: str) -> bytes`: `graph_get_json(f"/{media_id}")`; raises `ApiError(413, "file_too_large")` if `file_size > files.MAX_BYTES`, `ApiError(415, "unsupported_file")` unless the URL starts with `MEDIA_PREFIX = "https://lookaside.fbsbx.com/"`; then `graph_get_bytes(url)`, reading at most `MAX_BYTES + 1`.
  - Module-level `graph_post(path: str, body: dict) -> dict`, `graph_get_json(path: str) -> dict`, `graph_get_bytes(url: str) -> bytes`: httpx, bearer `wa_access_token`, timeout 20 s, raise on non-2xx. Tests monkeypatch these three.

- [ ] **Step 1: Failing tests** (no DB)

```python
def test_signature_ok_and_forged():
    body, secret = b'{"a":1}', "s3cret"
    good = "sha256=" + hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
    assert verify_signature(body, good, secret)
    assert not verify_signature(body + b" ", good, secret)
    assert not verify_signature(body, None, secret)
    assert not verify_signature(body, good, "")

def test_parse_text_document_image_status_and_junk(): ...
    # Meta-shaped payload: one text, one document, one image, one sticker, one status entry,
    # one sender "15550001111" (not Indian) -> [text, media, media, other]; sender "+919876543210"
def test_parse_malformed_never_raises():
    assert parse({}) == [] and parse({"entry": [{"changes": "x"}]}) == []

def test_split_limits_and_round_trip():
    paras = ["a" * 300, "b" * 300, "c" * 300]
    chunks = split(paras)
    assert all(len(c) <= 700 for c in chunks)
    assert "\n\n".join(chunks) == "\n\n".join(paras)
def test_split_long_paragraph_cuts_at_space(): ...  # 1500 chars of words: every chunk <= 700, words preserved

def test_templates_and_copy_carry_no_numbers():
    for table in (TEMPLATES, COPY):
        for name, langs in table.items():
            for text in langs.values():
                assert not re.search(r"\d", text), name
                assert set(re.findall(r"{(\w+)}", text)) <= {"lab"}, name

def test_report_paragraphs_refuses_red(): ...
def test_report_paragraphs_order(): ...  # statements, doctor note, closing line

def test_send_without_token_logs_only(monkeypatch, caplog): ...  # graph_post not called
def test_send_text_and_template_bodies(monkeypatch): ...        # token set; captured bodies match Meta shape

def test_fetch_media_checks_size_and_host(monkeypatch): ...
    # file_size too big -> 413; url "https://evil.example/x" -> 415; lookaside url -> bytes
```

- [ ] **Step 2:** Run `uv run pytest tests/test_whatsapp.py -q`. Expected: FAIL (import error).
- [ ] **Step 3:** Implement `files.check_bytes` and the module. HI copy under the machine-drafted comment.
- [ ] **Step 4:** Run `tests/test_whatsapp.py tests/test_reports_api.py`. Expected: PASS.
- [ ] **Step 5:** Commit `feat: whatsapp adapter (parse, signature, split, send, media)`.

---

### Task 3: Webhook — TDD

**Files:**
- Create: `backend/app/wa_api.py`
- Modify: `backend/app/main.py` (include router; redact the webhook query string in `uvicorn.access`), `backend/tests/test_canary.py` (public prefix `/api/whatsapp/webhook`)
- Test: `backend/tests/test_wa_webhook.py`

**Interfaces:**
- Consumes: `whatsapp.parse`, `whatsapp.verify_signature`.
- Produces: `router = APIRouter(prefix="/api/whatsapp")`;
  - `GET /api/whatsapp/webhook?hub.mode=subscribe&hub.verify_token=…&hub.challenge=…` → `PlainTextResponse(challenge)` when mode is `subscribe` and the token equals a non-empty `settings.wa_verify_token` (`hmac.compare_digest`), else 403.
  - `POST /api/whatsapp/webhook`: `settings.wa_app_secret` empty → 503 `whatsapp_unconfigured`; body over 1 MB → 413; bad signature → 401 `bad_signature`; bad JSON with a good signature → 200 (logged). For each `Inbound`: tenant from `SELECT id FROM tenants WHERE wa_phone_number_id = %s` (pool connection, no tenant; unknown → skip, log); in `db.tenant_tx(TenantCtx(tid))`: `INSERT INTO wa_inbound (message_id, tenant_id, sender_fp, body_enc) … ON CONFLICT DO NOTHING RETURNING message_id`; on insert, `INSERT INTO jobs … 'wa.inbound', {"message_id": …}`. Returns `{"status": "ok"}`.
  - `body_enc` = tenant cipher encryption of `json.dumps(dataclasses.asdict(inbound))`; `sender_fp` = `cipher.fingerprint(inbound.sender)`.
- `RedactShareTokens` (rename to `RedactSecrets`) also cuts the query string from any `/api/whatsapp/webhook?…` path.

- [ ] **Step 1: Failing tests** (helper `signed(client, payload, secret)` posts with the header; monkeypatch `settings.wa_app_secret`/`wa_verify_token`; a lab with `wa_phone_number_id` set via owner SQL)

```python
def test_verify_handshake(client, monkeypatch): ...      # right token -> 200 body == challenge; wrong -> 403; empty setting -> 403
def test_unconfigured_secret_is_503(client): ...
def test_forged_signature_401_and_no_rows(client, wa_lab): ...
def test_text_message_stored_encrypted_and_one_job(client, wa_lab): ...
    # wa_inbound row: body_enc is not plaintext (no "hello" bytes), sender_fp set; one 'wa.inbound' job,
    # payload == {"message_id": "wamid.1"}
def test_duplicate_delivery_one_job(client, wa_lab): ...  # same payload twice -> 200, 200; one row, one job
def test_unknown_business_number_ignored(client, wa_lab): ...  # 200, no rows
def test_status_only_payload_ignored(client, wa_lab): ...
def test_access_log_redacts_verify_token(): ...           # filter on a record with the query path -> no token
```

- [ ] **Step 2:** Run `uv run pytest tests/test_wa_webhook.py tests/test_canary.py -q`. Expected: FAIL (404s).
- [ ] **Step 3:** Implement. Read the raw body with `await request.body()` in an `async def` route; do the DB work through `run_in_threadpool`.
- [ ] **Step 4:** Run the same tests. Expected: PASS.
- [ ] **Step 5:** Commit `feat: whatsapp webhook with signature check and dedupe`.

---

### Task 4: Link routes — TDD

**Files:**
- Modify: `backend/app/wa_api.py`
- Test: `backend/tests/test_wa_link.py`

**Interfaces:**
- Consumes: `auth._code_hash`, `auth.Own`, Task 1 tables.
- Produces (patients only, `Own`; any other role 404):
  - `GET /api/whatsapp/link` → `{"available": bool, "lab_number": str | None, "linked": bool, "number_masked": str | None, "opted_in": bool}`; audited `read wa_link`.
  - `POST /api/whatsapp/link-code` body `{"language": "en" | "hi"}` → 201 `{"code": "123456", "lab_number": "+1555…", "expires_in": 600}`. Lab without a number → 409 `whatsapp_unavailable`. More than 3 codes in 10 min for this user → 429 `too_many_requests`. Earlier unused codes of the user are marked used. A new code whose hash matches another live code in the tenant is redrawn (up to 5 tries). The language goes to `wa_link_codes.lang`.
  - `DELETE /api/whatsapp/link` → 204: deletes the user's `wa_links` row and withdraws `whatsapp` consent; audited.
- Module constants: `CODE_TTL = "10 minutes"`, `CODE_MAX_PER_10_MIN = 3`.

- [ ] **Step 1: Failing tests**

```python
def test_status_unlinked(client, patient, wa_lab): ...       # available True, lab_number, linked False
def test_link_code_shape_and_hash_only(client, patient, wa_lab, db_urls): ...
    # 6 digits; DB holds code_hash != code bytes; expires ~10 min
def test_link_code_rate_limited(client, patient, wa_lab): ...  # 4th within 10 min -> 429
def test_no_number_is_409(client, patient): ...
def test_staff_and_profile_get_404(client, lab, login): ...   # staff login; patient with X-Profile
def test_code_unique_among_live_codes(monkeypatch, client, patient, wa_lab): ...
    # monkeypatch secrets.randbelow to return a live code first, then another: the second is issued
def test_unlink_deletes_and_withdraws(client, patient, wa_lab, db_urls): ...
```

- [ ] **Step 2:** Run `uv run pytest tests/test_wa_link.py -q`. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5:** Commit `feat: whatsapp link codes and link status`.

---

### Task 5: Inbound worker — commands and media — TDD

**Files:**
- Create: `backend/app/wa_jobs.py`
- Modify: `backend/app/worker.py` (`HANDLERS["wa.inbound"]`)
- Test: `backend/tests/test_wa_inbound.py`

**Interfaces:**
- Consumes: Task 2 `Inbound`, `COPY`, `send`, `fetch_media`, `report_paragraphs`, `split`; `files.check_bytes`; `reports.create_report`, `attach_file`, `report_detail`, `held_for`.
- Produces:
  - `wa_jobs.inbound(job: dict, models: dict | None, saver) -> None`, registered as `HANDLERS["wa.inbound"]`.
  - Every send goes through `whatsapp.send` with the tenant's `wa_phone_number_id`.
  - `UNLINKED_MAX_PER_HOUR = 10`, `WA_CONSENT_VERSION = "wa-2026-11-v1"`.

Flow (worker role transaction `db.owner_tx(settings.worker_database_url, tid)`; never hold a transaction across a Graph call or a model call):
1. Load the `wa_inbound` row; missing or `body_enc IS NULL` (done) → return. Decrypt the `Inbound`. Find the link by `sender_fp`.
2. **Unlinked:** more than `UNLINKED_MAX_PER_HOUR` rows from this `sender_fp` in the last hour → drop. `LINK <code>` with a live, unused code (hash match, `expires_at > now()`) → mark used, delete any link with this `wa_fp` or this `user_id`, insert the link (`wa_enc`, `lang` from the code row, `last_inbound_at = now()`), grant `whatsapp` consent (version `WA_CONSENT_VERSION`) if not active, reply `linked`. Bad code → `bad_code`. Anything else → `link_from_app`.
3. **Linked:** set `last_inbound_at = now()`. `STOP` → withdraw, reply `stopped`. `START` → grant, reply `started`. With `whatsapp` consent withdrawn → nothing else (no reply). No `core` consent → `consent_needed`.
4. `REPORT` → the latest report of the user (by `created_at`) with status `ready` or `needs_review`: none → `no_report`; red triage or `held_for` → `red` (W1); else `split(report_paragraphs(report_detail(...), lang))`, one send per chunk, then `ask_more`. `audit(c, TenantCtx(tid, user_id, "patient"), "read", "report", rid)`.
5. **Media:** `fetch_media` then `check_bytes` (outside any transaction); an `ApiError` → `bad_file`. Then in one transaction `create_report(c, TenantCtx(tid, user_id, "patient"), user_id, "whatsapp", "received")` + `attach_file`; reply `reading`. The pipeline and Task 7 do the rest.
6. Text that is not a command → Task 6's `question` (this task: reply `not_ready` as a placeholder that Task 6 replaces).
7. Finally `UPDATE wa_inbound SET body_enc = NULL`.

- [ ] **Step 1: Failing tests** (helper `deliver(client, wa_lab, sender, text=None, media_id=None)` posts a signed webhook and runs `worker.run_once()` until idle; `sent` fixture monkeypatches `whatsapp.graph_post` to record bodies and sets `settings.wa_access_token = "test"`)

```python
def test_unlinked_sender_told_to_link(...): ...           # one send with COPY link_from_app
def test_link_flow_links_and_opts_in(client, patient, wa_lab, sent): ...
    # code from POST /link-code; deliver "link 123456" -> wa_links row, whatsapp consent active,
    # GET /api/whatsapp/link shows linked; reply 'linked'
def test_link_expired_or_used_code_rejected(...): ...     # expired (owner SQL) -> bad_code; reuse -> bad_code
def test_relink_moves_number(...): ...                     # second patient links the same number: first loses it
def test_unlinked_sender_capped(...): ...                  # 11 messages in an hour: 10 replies
def test_stop_and_start(...): ...                          # consent withdrawn / re-granted; one reply each
def test_withdrawn_sender_gets_no_reply(...): ...          # after STOP, "REPORT" -> nothing sent
def test_report_command_sends_explanation(...): ...        # ready green report (stored via store_result helper used in test_worker) -> chunks contain its statement text
def test_report_command_red_sends_red_line(...): ...       # red report, released or held -> only COPY red; no digit of any result value in any sent text
def test_media_creates_whatsapp_report(...): ...           # graph fakes return lookaside url + pdf_bytes(); report source 'whatsapp', status received, one pipeline job, reply 'reading'
def test_media_bad_type_or_host(...): ...                  # PNG magic missing -> bad_file; evil host -> bad_file; no report row
def test_body_cleared_after_handling(...): ...
```

- [ ] **Step 2:** `docker compose stop worker`, then `uv run pytest tests/test_wa_inbound.py -q`. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run. Expected: PASS. Then the full suite.
- [ ] **Step 5:** Commit `feat: whatsapp inbound commands and media`.

---

### Task 6: One chat core, questions on WhatsApp — TDD

**Files:**
- Modify: `backend/app/chat_api.py`, `backend/app/wa_jobs.py`
- Test: `backend/tests/test_chat_api.py`, `backend/tests/test_wa_inbound.py`

**Interfaces:**
- Produces:
  - `chat_api.converse(tx: Callable[[], ContextManager], ctx: TenantCtx, report_id: UUID, question: str, lang: str, model: BaseChatModel | None, channel: Literal["web", "whatsapp"], allow_red: bool = True) -> ChatReply`: the current POST body moved verbatim (visible, held 409 `under_review`, status 409 `report_not_ready`, 429 `too_many_messages`, history, model call outside the transaction, store both messages with `channel`, gated → review item, audit). With `allow_red=False` a report with `triage = 'red'` raises `ApiError(409, "red_result")` before any model call.
  - The POST route calls `converse(lambda: db.tenant_tx(ctx), …, channel="web")`. GET history adds `"channel"` to each message.
  - In `wa_jobs`, a non-command text from a linked, consented sender: latest chat-ready report (as REPORT); none → `no_report`; `converse(worker tx, …, models.get("chat") if models else None, "whatsapp", allow_red=False)`; `ApiError` 409 `under_review`/`red_result` → `red`; 429 → `too_many`; else split the reply text and send.
  - `question` length: WhatsApp text is cut to 500 characters (the web limit) before `converse`.

- [ ] **Step 1: Failing tests**

```python
def test_web_history_has_channel(client, patient, ...): ...            # existing chat test + "channel": "web"
def test_question_on_whatsapp_stored_with_channel(...): ...            # fake chat model; reply sent; chat_messages channel 'whatsapp'
def test_conversation_continues_across_channels(...): ...
    # ask on web, then on WhatsApp: the fake model's received messages include the web turn;
    # GET /api/reports/{id}/chat lists all four in order with their channels
def test_question_on_red_report_refused(...): ...                      # model never called; only COPY red
def test_hourly_limit_counts_both_channels(...): ...                   # 29 web + 1 WA ok, next WA -> too_many
def test_gated_whatsapp_answer_opens_review(...): ...                  # fake model output fails the gate -> review item kind chat
```

- [ ] **Step 2:** Run `uv run pytest tests/test_chat_api.py tests/test_wa_inbound.py -q`. Expected: FAIL.
- [ ] **Step 3:** Implement; existing web chat tests stay unchanged except the new key.
- [ ] **Step 4:** Run, then the full suite. Expected: PASS.
- [ ] **Step 5:** Commit `feat: one chat core for web and whatsapp`.

---

### Task 7: Outbound events — TDD

**Files:**
- Modify: `backend/app/wa_jobs.py`, `backend/app/worker.py` (`_save`, `_review_job`, `run_once`, `_sweep_dead`, `HANDLERS["wa.notify"]`), `backend/app/reports.py` (`store_result` trend hook)
- Test: `backend/tests/test_wa_notify.py`, `backend/tests/test_worker.py`

**Interfaces:**
- Produces:
  - `wa_jobs.queue_notify(c, tenant_id: UUID, user_id: UUID, event: Literal["report_ready", "review_complete", "trend_alert"], report_id: UUID | None = None) -> None`: inserts a `wa.notify` job only when the user has a `wa_links` row.
  - Call sites: `worker._save` after `store_result` (`report_ready`, also when `res.pending`: the handler decides), `worker._review_job` after `store_result` (`review_complete`), `reports.store_result` once if `refresh_trends` returned any new trend (`trend_alert`).
  - `wa_jobs.notify(job, models, saver) -> None`: link gone, or `whatsapp` consent not active → return. Report deleted → return. Held (`held_for` as the patient) → return. In window (`last_inbound_at > now() - 24 h`): `report_ready` on a red report → text `COPY red`; `report_ready` otherwise → explanation chunks then `ask_more`; `review_complete`/`trend_alert` → the template's text as free text. Outside the window: template `report_ready_red` for red, else the event's template, with `lab = tenants.name`.
  - `worker.run_once`/`_sweep_dead`: a report id is read from the payload only when `job["kind"] == "report.pipeline"` (W10).

- [ ] **Step 1: Failing tests**

```python
def test_no_link_no_job(...): ...                         # store a report for an unlinked user: no wa.notify job
def test_ready_in_window_sends_explanation(...): ...
def test_ready_outside_window_sends_template(...): ...    # last_inbound_at 2 days ago -> template body, name report_ready, no digit anywhere in body
def test_notify_held_sends_nothing(...): ...              # red report parked for review
def test_notify_released_red_has_no_values(...): ...      # doctor escalates -> review_complete; in and out of window: only red copy / report_ready_red template
def test_notify_after_stop_sends_nothing(...): ...        # job queued, then STOP, then run -> no send
def test_notify_after_delete_me(...): ...                 # job queued, user deletes data -> job done, no send
def test_trend_alert_once(...): ...                       # third rising HbA1c -> one trend_alert job
def test_notify_job_keeps_parked_thread(...): ...         # warnings report parked; run its wa.notify; doctor approves; resume stores the result
```

- [ ] **Step 2:** Run `uv run pytest tests/test_wa_notify.py tests/test_worker.py -q`. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run, then the full suite and ruff. Expected: PASS.
- [ ] **Step 5:** Commit `feat: whatsapp report, review and trend alerts`.

---

### Task 8: Web — link section and channel tag

**Files:**
- Create: `web/src/WhatsApp.tsx`
- Modify: `web/src/api.ts`, `web/src/pages/Profile.tsx`, `web/src/Chat.tsx`, `web/src/i18n.tsx`
- Test: `web/src/waLink.test.ts` (pure helper)

**Interfaces:**
- Consumes: Task 4 routes; Task 6 `channel` on history.
- Produces: `api.waLink()`, `api.waLinkCode(language)`, `api.waUnlink()`; `type WaLink` matching Task 4; `ChatMessage.channel?: "web" | "whatsapp"`; `linkInstruction(code: string, labNumber: string): string` in `web/src/waLink.ts` returning `LINK 123456` (the exact text to send) for the copy button and display.

UI (impeccable, Clean Monochrome, existing `strip` pattern): a "WhatsApp" strip on Profile under Account, patients only. Not available → one hint line. Not linked → "Get a link code" button; then the code, the lab number, "Send LINK 123456 to +1555… on WhatsApp. The code works for 10 minutes." and a copy button. Linked → masked number, opted-in state, "Unlink" button. Chat: a small `chat__via` tag "via WhatsApp" on messages with `channel === "whatsapp"`. EN + HI keys (`waTitle`, `waUnavailable`, `waGetCode`, `waSendCode`, `waLinked`, `waOptedOut`, `waUnlink`, `viaWhatsApp`), Hindi under the machine-drafted comment.

- [ ] **Step 1: Failing test** `linkInstruction("042137", "+15550000001")` returns `"LINK 042137"`; the i18n parity test (existing) catches missing HI keys.
- [ ] **Step 2:** `npx vitest run`. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** `npx vitest run; npx tsc -b; npm run lint; npm run build`. Expected: clean. `docker compose restart web`; on http://localhost:5173 as patient `+919000000001`, Profile shows the strip and a code.
- [ ] **Step 5:** Commit `feat: whatsapp link section and chat channel tag`.

---

### Task 9: Dev tool, parity evals, results

**Files:**
- Create: `scripts/wa_fake.py`
- Modify: `evals/run.py` (`SUITES["whatsapp"]`), `.github/workflows/ci.yml` (add the suite after `held`), `evals/RESULTS.md`, `phases/phase-3-whatsapp.md` (tick boxes)
- Test: the suite itself

**Interfaces:**
- `scripts/wa_fake.py --from +919000000001 --text "LINK 123456" [--to dev-alpha] [--url http://localhost:8000]`: builds a Meta-shaped payload with a random `wamid`, signs it with `WA_APP_SECRET` from the environment, posts it, prints the status. Text only (media needs the Graph API). Replies show in `docker compose logs worker` (log-only send).
- `run_whatsapp() -> list[tuple[str, bool, str]]`, cases:
  - every non-red fixture spec through `template_result` + `_patient_detail`: `split(report_paragraphs(detail, lang))` for EN and HI has every chunk `<= 700`, and joined back equals `"\n\n".join(paragraphs)`; the paragraphs contain every explanation statement of the web detail and its closing line (same next step);
  - every red fixture spec: `report_paragraphs` raises, and the red copy and `report_ready_red` template contain no result value;
  - every `TEMPLATES`/`COPY` text: no digit, no placeholder but `{lab}`.

- [ ] **Step 1:** Add the suite; run `uv run python ../evals/run.py whatsapp`. Expected: all pass (fix code, never the case, if one fails).
- [ ] **Step 2:** Manual check with the dev stack: `docker compose up -d --build api worker`; set `WA_APP_SECRET=dev-secret` in `.env` for the api; get a code in the app, `uv run python ../scripts/wa_fake.py --from +919000000001 --text "LINK <code>"`, then `--text "REPORT"`; the worker log shows the linked reply and the explanation.
- [ ] **Step 3:** Full backend suite (`rtk proxy uv run pytest -q -m "not live"` with the worker stopped), ruff, web checks, all eval suites; record counts in `RESULTS.md`; tick the spec's Done-when boxes that the tests prove.
- [ ] **Step 4:** Commit `test: whatsapp parity evals and dev webhook tool`.
- [ ] **Step 5:** Ask the user before running `security-review` (spec Done-when: webhook, media download, number linking) and the final whole-branch review.
