# Phase 3.1: Red shown at once, fixes, Telegram — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** a patient reads every report, red included, as soon as it is ready, with an urgent banner. The same patient can link a Telegram bot and use it like the WhatsApp channel.

**Architecture:**
- The red hold goes: `visibility.py` is deleted, and every patient door returns the report the staff see. Doctor review still parks red and warnings reports, but nothing waits on it.
- The WhatsApp tables and job kinds become channel-neutral (`channel_links`, `link_codes`, `inbound_messages`, `msg.inbound`, `msg.notify`). `wa_jobs.py` becomes `msg_jobs.py`, one shared handler that picks an adapter by channel.
- `app/telegram.py` is the second adapter. `app/telegram_poll.py` is a long-polling service that stores updates exactly as the webhook does.
- Replies are parked encrypted in the inbound row before they are sent, so a failed send is retried and never lost.

**Tech Stack:** unchanged (FastAPI, psycopg 3, Postgres 16 RLS, LangGraph, React 19 + Vite, httpx). No new package.

**Spec:** [phase-3.1-telegram.md](phase-3.1-telegram.md). Phase 3 plan for conventions: [phase-3-tasks.md](phase-3-tasks.md).

## Before starting (user actions)

1. Nothing for tests: every test fakes the Telegram and Graph APIs.
2. For the live check (Task 9): create a bot with @BotFather and set `TELEGRAM_BOT_TOKEN`, `TELEGRAM_BOT_USERNAME` and `TELEGRAM_LAB=lab-alpha` in `.env`.

## Rulings made while planning

| # | Decision | Why | Cost if wrong |
|---|---|---|---|
| T1 | **Red is shown at once (controller).** `visibility.py` is deleted, along with `reports._held`, `reports.held_for`, `report_detail(staff=…)`, `converse(allow_red=…)` and every `under_review` branch. A parked red report reads `status = "needs_review"` and `review_pending = true`, like a warnings-only one today, so the web shows its values with the existing `reviewPending` line. The lab-file gate keeps only "not before triage", now 409 `report_not_ready`. Share `_why_not` keeps only `report_not_ready`. The SSE `needs_review` re-read goes. *Supersedes Q6 and W1.* | Spec A | none |
| T2 | **The urgent line comes first, exactly once.** `pipeline._frame` already stores `urgent_message(lang)` as statement 0 of every red report. `whatsapp.report_paragraphs` therefore prepends it only when it is missing (no explanation in either language), and never raises. `COPY["red"]` is deleted: no path needs it any more. The `report_ready_red` template stays for the WhatsApp out-of-window case (no values in templates, the Meta rule). | Prepending without checking would send the line twice | none |
| T3 | **Banner in two steps.** Task 1 adds the banner text: `urgentBanner` EN = "One or more results need attention today. Please call your lab or a doctor.", above the triage strip on a red report and on the Dashboard summary. The call button needs `tenants.phone`, which arrives with `008` in Task 3. Task 8 adds it: the patient's `report_detail` carries `lab_phone` (`tenants.phone`, possibly null) only when `triage == "red"`. The seed sets lab-alpha to `+911140000000`. | Keeps one migration, `008_channels.sql` (controller) | the banner has no call button for Tasks 1–7 (branch only) |
| T4 | **Lost replies: an outbox in `body_enc`, with no schema change.** The decide transaction does the effects (link, consent, report, chat turn) and overwrites `body_enc` with `encrypt({"outbox": [texts], "to": address})` in the same transaction. The sends follow, and only then is `body_enc` set to NULL. A retry that finds an outbox only resends it. So LINK, STOP, START and media are idempotent by construction; a duplicate reply is possible and a lost one is not. | Spec B. Clearing after the sends alone would answer a retried LINK with `bad_code` and make a second report from a retried media message | a crash between `converse` committing and the outbox write re-asks once (a duplicate chat turn). ponytail note in code |
| T5 | **One "latest report" order.** `ORDER BY coalesce(collected_on, created_at::date) DESC, created_at DESC, id DESC`, in `msg_jobs._latest` and in `reports.list_reports` (which gains the `id` tie-break) | Spec B: the same order as the list | none |
| T6 | **Generalise, don't duplicate (controller).** `008_channels.sql` makes these changes:<br>• renames `wa_links`→`channel_links`, `wa_link_codes`→`link_codes`, `wa_inbound`→`inbound_messages`, and `wa_fp`/`wa_enc`→`address_fp`/`address_enc`;<br>• adds `channel` (CHECK whatsapp/telegram) to both link tables, default `'whatsapp'` and then the default dropped;<br>• replaces the unique keys with `(tenant_id, user_id, channel)` and `(tenant_id, channel, address_fp)`;<br>• adds `tenants.phone`;<br>• widens `reports.source` and `chat_messages.channel` to include `telegram`.<br>Policies and grants follow a renamed table. The implementer reads the old constraint names from `pg_constraint` before dropping them. | One implementation for both channels (spec C) | none |
| T7 | **Job kinds `msg.inbound {"message_id", "channel"}` and `msg.notify {"user_id", "event", "channel", "report_id"?}`.** `wa.inbound` and `wa.notify` stay in `HANDLERS` as aliases. A payload with no `channel` means `whatsapp`. `queue_notify` inserts one `msg.notify` per `channel_links` row of the user. | Jobs already queued at deploy time still run (controller) | none |
| T8 | **Adapter surface.** `whatsapp` and `telegram` each expose:<br>• `CHUNK`;<br>• `COPY` (same keys; Telegram adds `review_complete` and `trend_alert`);<br>• `command(text) -> tuple[Literal["link","stop","start","report"], str | None] | None`;<br>• `send_text(account: str, to: str, text: str) -> None`;<br>• `fetch_media(media_id: str) -> bytes`.<br>`msg_jobs.ADAPTERS` maps the channel to its module. `Inbound`, `split` and `report_paragraphs` stay in `whatsapp.py` (they are channel-neutral) and keep their field names, because already-stored rows decode as `Inbound(**json)`. Telegram builds `Inbound(message_id, phone_number_id="", sender=str(chat_id), …)`. | The least churn. Renaming the `Inbound` fields would break the ciphertext of queued rows | none |
| T9 | **Link routes are generic, and the WhatsApp ones stay as aliases.** The generic routes live in `channels_api.py`: `GET`/`DELETE /api/channels/{channel}/link` and `POST /api/channels/{channel}/link-code`. The phase 3 `/api/whatsapp/link*` routes become three one-line aliases, so `test_wa_link.py` proves the rename unchanged. The web moves to the generic routes in Task 8. | The phase 3 suite is the proof of "no behaviour change" | three tiny routes to delete later |
| T10 | **Everything about linking is per channel:**<br>• a code is redeemed only on its own channel;<br>• a new code supersedes only that channel's codes;<br>• the 3-per-10-min limit is per (user, channel);<br>• unlink withdraws only that channel's consent purpose;<br>• `/stop` stops only Telegram.<br>Purposes and versions: `whatsapp` `wa-2026-11-v1`, `telegram` `tg-2026-11-v1`. | Otherwise a Telegram code kills a live WhatsApp code, or a WhatsApp code links a Telegram chat | none |
| T11 | **Telegram link code:**<br>• `secrets.token_urlsafe(32)` (43 characters), HMAC with `otp_pepper` (`auth._code_hash`), 10 minutes, single use, no redraw (2²⁵⁶);<br>• `POST …/telegram/link-code` returns `{"url": "https://t.me/<username>?start=<code>", "expires_in"}`;<br>• Telegram is available only when the token and username are set and the tenant's slug equals `telegram_lab`. Otherwise GET says `available: false` and POST is 409 `telegram_unavailable`. | Spec C, controller 5 | none |
| T12 | **Poller offset kept in memory, nothing stored.** Telegram keeps unconfirmed updates for 24 h and confirms them only when `getUpdates` is called with a higher offset. The poller passes `max(update_id)+1` after the rows commit, and starts with no offset after a restart, which re-reads what was not confirmed. The inbound primary key makes a re-read a no-op. `allowed_updates=["message"]`, one replica, role `hc_app` (the webhook's role and grants). | Zero state is strictly enough: Telegram is the offset store | a restart after more than 24 h down loses updates (Telegram's limit either way) |
| T13 | **Inbound id `tg:<bot_id>:<update_id>`**, where `bot_id` is the token's part before `:` (not secret). | Update ids are per bot: a replaced bot could reuse a number and be dropped silently as a duplicate | none |
| T14 | **The token never reaches a log.** It sits in every Bot API URL, file downloads included:<br>• `tg_call` and `tg_get_bytes` re-raise any `httpx.HTTPError` as `TelegramError(f"{method} failed: {status}")` `from None`;<br>• `telegram.py` sets the `httpx` logger to WARNING at import, since httpx logs each URL at INFO.<br>WhatsApp is unaffected (its token is in a header). | The worker's `log.exception` would otherwise print the token | none |
| T15 | **Telegram media.**<br>• A `document`, or a `photo` (the last size, which Telegram lists ascending), is kind `media` with its `file_id`;<br>• `getFile`: `file_size > MAX_BYTES` → 413;<br>• a `file_path` that is empty, starts with `/`, or contains `..`, `//` or `:` → 415;<br>• the download URL is always `https://api.telegram.org/file/bot<token>/<file_path>`, read capped at `MAX_BYTES + 1`, then the same `files.check_bytes`.<br>Groups, channels, edited messages and other update types → `parse_update` returns None. | Spec C limits; only `api.telegram.org` is ever fetched | none |
| T16 | **Telegram commands** (trimmed, case-insensitive):<br>• `/start <code>` → link;<br>• `/start` → start (an unlinked chat gets `link_from_app`);<br>• `/stop`, `/report`;<br>• any other text → question.<br>The unlinked cap (`UNLINKED_MAX_PER_HOUR`) applies to Telegram too. Telegram has no window and no templates: alerts are always free text. | Spec C | none |

## Global Constraints

- Every phase 1–3 Global Constraint still holds:
  - tenant tables with RLS forced and composite FKs;
  - `ApiError`; the same 404 for missing and forbidden; audit on every patient read;
  - no network in tests; the model never decides anything clinical;
  - no PHI in logs or job payloads (ids only);
  - commit as `subhrajeet.diaz@gmail.com` with no AI attribution or co-author trailer.
- No real keys anywhere. Tests monkeypatch `telegram.tg_call`, `telegram.tg_get_bytes`, `whatsapp.graph_post`, `whatsapp.graph_get_json` and `whatsapp.graph_get_bytes`. With no token, `send_text` only logs, with the text only when `env != "prod"`.
- Job kinds (exact): `msg.inbound`, `msg.notify`, and the aliases `wa.inbound` and `wa.notify`.
- Consent purposes (exact): `core`, `whatsapp`, `telegram`. Report sources (exact): `patient`, `lab`, `whatsapp`, `telegram`. Chat channels (exact): `web`, `whatsapp`, `telegram`.
- Chunks: `whatsapp.CHUNK = 700`, `telegram.CHUNK = 4096`.
- Settings (all default `""`): `telegram_bot_token`, `telegram_bot_username`, `telegram_lab`.
- Hindi copy is machine-drafted; mark it with the same comment as `Consent.tsx`.
- Run `docker compose stop worker` before the backend suite: `rtk proxy uv run pytest -q -m "not live"` from `backend/`.
- After every web edit, run `docker compose restart web`.
- Never `docker compose down -v`.

## Review Focus

1. **The bot token lands in a log or an error message.** Expected: no log record and no exception text contains the token; the httpx logger is at WARNING. Test: Task 4 `test_tg_call_error_and_logs_hide_token`.
2. **A retried job double-links, makes two reports, or loses its reply.** Expected: a failed send is resent on retry. A retried LINK still answers `linked`, with one link and one consent. A retried media message makes one report. Tests:
   - Task 2: `test_failed_send_is_retried_and_arrives`, `test_retried_link_links_once`, `test_retried_media_one_report`;
   - Task 6: `test_tg_failed_send_retried`.
3. **A red report loses its urgent line, or shows it twice.** Expected: the first paragraph on every channel and the first explanation statement on the web is the urgent line, exactly once. The patient sees values while the doctor review is still pending. Tests:
   - Task 1: `test_red_pending_shown_everywhere`, `test_report_paragraphs_red_urgent_first_once`;
   - Task 7: `test_tg_ready_red_urgent_first`;
   - Task 9: eval `telegram`.
4. **The wrong account gets linked.** Covers a group chat or an edited message, and a code redeemed on the other channel. Expected: no link, `bad_code` for a cross-channel code, and nothing stored from a group. Tests: Task 4 `test_parse_update_ignores_groups_edits_and_junk`; Task 6 `test_code_only_redeems_on_its_channel`.
5. **`/stop` on one channel leaks into the other, or an alert already queued is sent after `/stop`.** Expected: nothing goes to Telegram after `/stop`, and WhatsApp still sends. Test: Task 7 `test_tg_stop_leaves_whatsapp_on`.

---

### Task 1: Red results shown at once — backend, web, evals

**Files:**
- Delete: `backend/app/visibility.py`
- Modify:
  - backend: `backend/app/reports.py`, `privacy.py`, `share.py`, `timeline.py`, `chat_api.py`, `wa_jobs.py`, `whatsapp.py`, `doctor.py` (drop `staff=True`);
  - web: `web/src/pages/Report.tsx`, `pages/Dashboard.tsx`, `pages/ChatPage.tsx`, `pages/Timeline.tsx`, `api.ts`, `steps.ts`, `words.ts`, `i18n.tsx`;
  - evals and CI: `evals/run.py`, `.github/workflows/ci.yml` (`held` → `red`).
- Test: `backend/tests/test_visibility.py`, `test_share.py`, `test_timeline.py`, `test_whatsapp.py`, `test_wa_inbound.py`, `test_wa_notify.py`, `test_doctor.py`; `web/src/steps.test.ts`, `web/src/i18n.test.ts`

**Interfaces:**
- Produces:
  - `reports.report_detail(c, report: dict) -> dict`: the same for every role, with no hold.
  - `reports.TERMINAL = {"ready", "needs_review", "failed"}`.
  - `chat_api.converse(tx, ctx, report_id, question, lang, model, channel) -> ChatReply`: no `allow_red`, no `under_review` 409; `GET …/chat` likewise.
  - `whatsapp.report_paragraphs(detail, lang) -> list[str]`: never raises. On red, `paras[0] == urgent_message(lang)`, exactly once.
  - `wa_jobs._REFUSED = {"report_not_ready": "not_ready", "too_many_messages": "too_many", "not_found": "no_report"}`.
  - `wa_jobs.notify` no longer returns early for a pending review. In the window, red sends the explanation; outside it, the `report_ready_red` template.
- Web:
  - `"under_review"` leaves `Status`, `TERMINAL`, `steps.ts` and `STATUS`. The Timeline trend pill uses the new key `trendInReview` ("Under review"), and `ChatPage` always shows `chatNone`.
  - New key `urgentBanner` (T3).
  - Keys deleted: `heldLine`, `heldBody`, `chatHeld`, the `under_review` error copy, and the matching `i18n.test` case.

- [ ] **Step 1: Failing tests.** Rewrite the hide tests and delete the dead ones:
  - in `test_visibility`: `test_held_needs_red_and_a_pending_review`, `test_patient_view_strips_a_held_detail_only`, `test_sse_later_events_say_under_review`, `test_detail_read_mid_pipeline_does_not_leak`, `test_export_read_mid_pipeline_does_not_leak` and `_RunsWorkerOnce`;
  - in `test_whatsapp`: `test_report_paragraphs_refuses_red_and_held`, and the `COPY["red"]` assertion in `test_copy_and_template_keys_and_red_lines`;
  - in `test_wa_inbound`: the `under_review` and `red_result` rows of the refusal parametrize.

```python
# test_visibility.py
def test_red_pending_shown_everywhere(client, patient):  # Review Focus 3
    tid, rid, item = _park(client, patient)
    assert (item["status"], item["reason"]) == ("pending", "red")        # the doctor still gets it
    d = _detail(client, rid)
    assert (d["status"], d["triage"], d["review_pending"]) == ("needs_review", "red", True)
    assert d["results"][0]["flag"] == "critical"
    assert d["explanations"]["en"]["statements"][0]["text"] == URGENT_EN
    row = _listed(client, rid)
    assert row["triage"] == "red" and row["tests"]
    assert [e["status"] for e in _events(client, rid)] == ["needs_review"]
    assert _ask(client, rid, "Do I have cancer?").status_code == 200
    assert client.get(f"/api/reports/{rid}/chat").status_code == 200
    assert _exported(client, rid)[1]["results"]
    assert client.post("/api/share", json={"report_ids": [rid]}).status_code == 201
    assert any(p["report_id"] == rid for s in client.get("/api/timeline").json() for p in s["points"])

def test_lab_file_waits_for_triage_only(client, patient): ...
    # parked red lab file -> 200; a lab report still `received` -> 409 {"error": "report_not_ready"}

# test_whatsapp.py
def test_report_paragraphs_red_urgent_first_once():
    framed = _detail(triage="red", statements=[URGENT_EN, "Your Hemoglobin is 6 g/dL."])
    assert report_paragraphs(framed, "en")[0] == URGENT_EN
    assert report_paragraphs(framed, "en").count(URGENT_EN) == 1
    assert report_paragraphs(_detail(triage="red", statements=[]), "en")[0] == URGENT_EN

# test_wa_inbound.py
def test_report_command_red_sends_urgent_first(...): ...   # parked red: texts[0] starts with URGENT_EN, then ask_more
def test_question_on_red_report_answered(...): ...         # fake model called; reply sent; chat row channel 'whatsapp'
# test_wa_notify.py
def test_notify_parked_red_sends_now(...): ...             # in window: texts[0] == URGENT_EN at save time, no wait for the doctor
def test_notify_red_outside_window_template_only(...): ... # template report_ready_red; no digit in the body
# test_share.py: the 409 under_review case becomes "a parked red report is shareable and shown"
# test_timeline.py: the held tests become "a parked red report is a point; its trend shows"
```

- [ ] **Step 2:** `docker compose stop worker`, then `uv run pytest tests/test_visibility.py tests/test_share.py tests/test_timeline.py tests/test_whatsapp.py tests/test_wa_inbound.py tests/test_wa_notify.py -q`. Expected: FAIL.
- [ ] **Step 3:** Implement T1/T2 in the backend. Web: delete the held strip (`Report.tsx` `held` branch, Dashboard `heldLine`, `ChatPage` `chatHeld`). Add `UrgentBanner({ phone }: { phone?: string | null })`, exported from `Report.tsx`: a `strip triage triage--red` with the `urgentBanner` text, rendered first in `ReportBody` when `report.triage === "red" && !shared`, and in the Dashboard summary when the latest report's triage is red. Evals: rename `run_held` to `run_red`. For each fixture spec, the patient detail keeps its results. For every red spec, `report_paragraphs(detail, lang)[0] == urgent_message(lang)` and it appears once (EN and HI). For every non-red spec, the urgent line is absent. In `_whatsapp_spec`, red specs are checked like the others plus urgent-first. CI runs `red` in place of `held`.
- [ ] **Step 4:** Run the backend tests above, then the full backend suite; `uv run python ../evals/run.py red` and `… whatsapp`; `npx vitest run; npx tsc -b; npm run lint; npm run build`. Expected: all PASS, `red: 15/15`. Then by hand on http://localhost:5173: a red report shows the banner, its values and the "A doctor is also checking" line.
- [ ] **Step 5:** Commit `feat: red results shown at once with an urgent banner`.

---

### Task 2: Lost replies and the latest-report order — TDD

**Files:**
- Modify: `backend/app/wa_jobs.py`, `backend/app/reports.py` (`list_reports` order)
- Test: `backend/tests/test_wa_inbound.py`

**Interfaces:**
- Produces, in `wa_jobs`:
  - `_outbox(c, cipher, message_id: str, to: str, texts: list[str]) -> None`: overwrites `body_enc` with `encrypt(json.dumps({"outbox": texts, "to": to}))`.
  - `_deliver(tid: UUID, message_id: str) -> None` (Task 3 adds `channel: Channel`): reads the outbox, sends every text, then sets `body_enc = NULL`. A send that raises propagates, so the worker retries.
  - `inbound` itself: a row whose decrypted JSON has `"outbox"` goes straight to `_deliver`. Every path ends in `_outbox` written in the same transaction as its effects: the decide transaction, the media transaction (`create_report` + `attach_file`), the bad-file transaction, and a new transaction right after `converse`.
- `_latest` and `list_reports` use the T5 order.

- [ ] **Step 1: Failing tests.** Add a `flaky` fixture: `graph_post` raises `httpx.ConnectError("down")` on its first call, then records like `sent`. Add a helper `_due(tid)`: `UPDATE jobs SET run_after = now() WHERE status = 'queued'`.

```python
def test_failed_send_is_retried_and_arrives(client, patient, wa_lab, flaky): ...
    # linked; ready report; deliver "REPORT" -> nothing recorded, job queued with attempts 1;
    # _due; run_once -> recorded texts == the report chunks + ask_more; body_enc NULL
def test_retried_link_links_once(client, patient, wa_lab, flaky): ...
    # "LINK <code>" with the first send failing; retry -> texts == [COPY linked en];
    # one wa_links row; exactly one active whatsapp consent row; code used
def test_retried_media_one_report(client, patient, wa_lab, flaky): ...
    # media with the first send failing; retry -> reply 'reading'; one report (source whatsapp),
    # one report.pipeline job
def test_latest_matches_report_list_order(client, patient, wa_lab, sent): ...
    # A created first with collected_on today, B later with collected_on a month ago:
    # REPORT sends A's statement text. Then equal collected_on and created_at (owner SQL):
    # the report REPORT reads == the first chat-ready id of GET /api/reports
```

- [ ] **Step 2:** `uv run pytest tests/test_wa_inbound.py -q`. Expected: the 4 new tests FAIL (the retry answers `bad_code`, or nothing arrives).
- [ ] **Step 3:** Implement T4 and T5. Add a ponytail comment at the `converse` → `_outbox` gap.
- [ ] **Step 4:** Run `tests/test_wa_inbound.py tests/test_wa_notify.py tests/test_reports_api.py`, then the full suite. Expected: PASS.
- [ ] **Step 5:** Commit `fix: whatsapp replies survive a failed send; one latest-report order`.

---

### Task 3: Channel-neutral rename — no behaviour change

**Files:**
- Create: `backend/app/migrations/008_channels.sql`, `backend/app/channels_api.py`
- Rename: `backend/app/wa_jobs.py` → `backend/app/msg_jobs.py` (`git mv`)
- Modify: `backend/app/wa_api.py` (webhook calls `msg_jobs.store_inbound`; link routes become aliases), `whatsapp.py` (`command`, `send_text`), `worker.py`, `reports.py`, `main.py` (include `channels_api.router`)
- Test: `backend/tests/test_schema.py`, `test_channels.py` (new). Mechanical edits only in `test_wa_inbound.py`, `test_wa_link.py`, `test_wa_notify.py`, `test_wa_webhook.py`, `test_worker.py`: the table, column and job-kind names, and `wa_jobs`→`msg_jobs`.

**Interfaces:**
- Consumes: Task 2 `_outbox`/`_deliver`.
- Produces:
  - Schema: T6.
  - `msg_jobs.Channel = Literal["whatsapp", "telegram"]`; `ADAPTERS: dict[str, ModuleType] = {"whatsapp": whatsapp}`; `CONSENT_VERSION = {"whatsapp": "wa-2026-11-v1"}`.
  - `msg_jobs.store_inbound(tid: UUID, channel: Channel, m: Inbound) -> bool`: one `db.tenant_tx`; `INSERT INTO inbound_messages … ON CONFLICT DO NOTHING RETURNING`; on insert, a `msg.inbound` job with `{"message_id", "channel"}`. Returns whether it inserted.
  - `msg_jobs.inbound(job, models, saver)` and `notify(job, models, saver)`: the channel comes from `payload.get("channel", "whatsapp")` (T7); sends go through `ADAPTERS[channel].send_text`.
  - `msg_jobs._deliver(tid: UUID, message_id: str, channel: Channel) -> None`: sends through the channel's adapter.
  - `msg_jobs._account(c, tid: UUID, channel: Channel) -> str | None`: for WhatsApp, `tenants.wa_phone_number_id`. None → replies dropped with a warning (as now), and `body_enc` is still set to NULL.
  - **Every link query is scoped by channel**, so the phase 3 SQL that assumed one channel is fixed here, not discovered in Task 6:
    - every `channel_links` read or delete filters `channel = %s`;
    - `_link` deletes `WHERE channel = %s AND (address_fp = %s OR user_id = %s)`;
    - `notify` selects the link by `(user_id, channel)`;
    - STOP, START, `_grant`, the active-purpose check and unlink use the purpose `channel` in place of the literal `'whatsapp'`.
  - `msg_jobs.queue_notify(c, tenant_id, user_id, event, report_id=None) -> None`: one job per link (T7).
  - `whatsapp.command(text: str) -> tuple[str, str | None] | None`, taking `LINK <6 digits>`, `STOP`, `START`, `REPORT`.
  - `whatsapp.send_text(account: str, to: str, text: str) -> None`: `send(Outbound(account, to, text=text))`.
  - `channels_api.router` (prefix `/api/channels`, patients only, as `wa_api._patient`): `GET`/`DELETE /{channel}/link` and `POST /{channel}/link-code`, with `channel: Literal["whatsapp"]` for now. The WhatsApp response shapes are exactly phase 3's. Codes, supersede, rate limit, lookups and unlink are all scoped by `channel` (T10). The audit entity is `channel_link`.
  - `worker.HANDLERS`: `msg.inbound`, `msg.notify`, `wa.inbound` and `wa.notify` (the last two pointing at the same functions).

- [ ] **Step 1: Failing tests**

```python
# test_schema.py
def test_phase3_tables_have_forced_rls(db_urls): ...  # now channel_links, link_codes, inbound_messages
def test_channel_unique_keys(db_urls): ...
    # one user: a whatsapp and a telegram link both insert; a second whatsapp link -> UniqueViolation;
    # the same address_fp on two channels -> ok; channel 'sms' -> CheckViolation
def test_tenant_phone_and_telegram_values(db_urls): ...  # tenants.phone nullable; source/channel 'telegram' ok

# test_channels.py
def test_generic_and_alias_routes_agree(client, patient, wa_lab): ...
    # GET /api/channels/whatsapp/link == GET /api/whatsapp/link; a code from either alias links
def test_unknown_channel_422(client, patient): ...   # /api/channels/sms/link -> 422
def test_legacy_wa_jobs_still_run(client, patient, wa_lab, sent): ...
    # store a message with the old payload shape and queue kind 'wa.inbound' {"message_id"} by owner SQL:
    # run_once handles it as whatsapp; a 'wa.notify' with no "channel" sends too
def test_queue_notify_one_job_per_link(client, patient, wa_lab): ...
    # a whatsapp link and a telegram link row (owner SQL) -> two msg.notify jobs, channels differ
```

- [ ] **Step 2:** Run `uv run pytest tests/test_schema.py tests/test_channels.py -q`. Expected: FAIL.
- [ ] **Step 3:** Write `008_channels.sql` with the nil-tenant preamble from 007. Do the rename. Make the mechanical test edits: no assertion changes, except the audit entity name if one is asserted.
- [ ] **Step 4:** Run the full backend suite and ruff. Expected: every phase 3 test green with only the mechanical edits. Run `uv run python -m app.migrate` against dev: it applies 008.
- [ ] **Step 5:** Commit `refactor: channel-neutral links, inbound and message jobs`.

---

### Task 4: Telegram adapter — TDD

**Files:**
- Create: `backend/app/telegram.py`
- Modify: `backend/app/config.py` (the three settings), `.env.example` (`TELEGRAM_BOT_TOKEN=`, `TELEGRAM_BOT_USERNAME=`, `TELEGRAM_LAB=lab-alpha`)
- Test: `backend/tests/test_telegram.py` (no DB)

**Interfaces:**
- Consumes: `whatsapp.Inbound` (T8), `files.MAX_BYTES`.
- Produces, in `telegram`:
  - Constants: `API = "https://api.telegram.org"`, `CHUNK = 4096`, `POLL_TIMEOUT = 30`, `TIMEOUT = 40`.
  - `class TelegramError(Exception)`.
  - `bot_id() -> str`: the token's part before `:`.
  - `parse_update(update: dict) -> Inbound | None` (T13, T15).
  - `command(text: str) -> tuple[str, str | None] | None` (T16). The `/start` code is accepted when it matches `[A-Za-z0-9_-]{1,64}`.
  - `COPY: dict[str, dict[str, str]]`, a superset of `whatsapp.COPY`'s keys plus `review_complete` and `trend_alert` (`{lab}` is the only placeholder). The command words are `/report`, `/stop` and `/start`, in EN + HI.
  - `send_text(account: str, to: str, text: str) -> None`: with no token, log only; otherwise `tg_call("sendMessage", {"chat_id": to, "text": text})`.
  - `fetch_media(file_id: str) -> bytes` (T15).
  - Module-level `tg_call(method: str, params: dict) -> dict`: POST `f"{API}/bot{token}/{method}"`, timeout `TIMEOUT`; it returns `result`, and raises `TelegramError` (T14) on non-2xx or `ok: false`. Module-level `tg_get_bytes(file_path: str) -> bytes`. Tests replace both.
  - At import: `logging.getLogger("httpx").setLevel(logging.WARNING)`.

- [ ] **Step 1: Failing tests**

```python
def test_parse_private_text_document_photo(): ...
    # text -> kind text; document -> media file_id; photo [s, m, l] -> media with l's file_id;
    # sticker -> other; message_id == f"tg:{bot}:{update_id}"; sender == str(chat.id); phone_number_id == ""
def test_parse_update_ignores_groups_edits_and_junk():  # Review Focus 4
    assert parse_update({"update_id": 1, "edited_message": PRIVATE_TEXT}) is None
    assert parse_update({"update_id": 2, "message": {**PRIVATE_TEXT, "chat": {"id": -5, "type": "group"}}}) is None
    assert parse_update({}) is None and parse_update({"update_id": 3, "message": "x"}) is None
def test_command_words():
    assert command("/start abc_-9") == ("link", "abc_-9") and command("/START") == ("start", None)
    assert command(" /stop ") == ("stop", None) and command("/report") == ("report", None)
    assert command("hello") is None and command("/start " + "a" * 65) is None
def test_copy_keys_and_no_numbers(): ...  # set(whatsapp.COPY) <= set(COPY); no digit; placeholders only {lab}; EN+HI
def test_send_without_token_logs_only(monkeypatch, caplog): ...
def test_send_text_calls_send_message(monkeypatch): ...  # params == {"chat_id": "42", "text": "hi"}
def test_fetch_media_size_path_and_cap(monkeypatch): ...
    # file_size MAX+1 -> 413; file_path "../x", "/x", "a//b", "http:x" -> 415; ok path -> tg_get_bytes(path) bytes
def test_tg_call_error_and_logs_hide_token(monkeypatch, caplog):  # Review Focus 1
    # settings token "123:SECRET"; httpx.post patched to return httpx.Response(401, request=…url with token…)
    # -> TelegramError; "SECRET" not in str(err), err.__suppress_context__ is True;
    # "SECRET" not in caplog.text; logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING;
    # the same for tg_get_bytes("documents/x.pdf") against a 404 from httpx.stream
```

- [ ] **Step 2:** `uv run pytest tests/test_telegram.py -q`. Expected: FAIL (import error).
- [ ] **Step 3:** Implement. HI copy goes under the machine-drafted comment.
- [ ] **Step 4:** Run `tests/test_telegram.py tests/test_whatsapp.py`. Expected: PASS.
- [ ] **Step 5:** Commit `feat: telegram adapter (parse, commands, send, media)`.

---

### Task 5: Poller service — TDD

**Files:**
- Create: `backend/app/telegram_poll.py`
- Modify: `docker-compose.yml` (service `telegram`: `build: ./backend`, `command: python -m app.telegram_poll`, `restart: unless-stopped`, `env_file: .env`, `DATABASE_URL` hc_app as `api`, owner/graph/admin URLs `""`, depends on `migrate`)
- Test: `backend/tests/test_telegram_poll.py`

**Interfaces:**
- Consumes: `telegram.parse_update`, `tg_call`, `POLL_TIMEOUT`; `msg_jobs.store_inbound`.
- Produces, in `telegram_poll`:
  - `store_update(tid: UUID, update: dict) -> bool`: `parse_update`, then `store_inbound(tid, "telegram", m)`. Returns False for an ignored update or a duplicate.
  - `poll_once(tid: UUID, offset: int | None) -> int | None`: `tg_call("getUpdates", {"timeout": POLL_TIMEOUT, "offset": offset, "allowed_updates": ["message"]})` (offset omitted when None). It stores each update and returns `max(update_id) + 1`, or `offset` when there were none (T12).
  - `serve(iterations: int | None = None, sleep=time.sleep) -> None`:
    - no token: log once (`"telegram off: no bot token"`), then `sleep(OFF_SLEEP_S)` each iteration;
    - unknown `telegram_lab` slug: log once, same sleep;
    - errors: logged and backed off 1, 2, 4 … `MAX_BACKOFF_S`, as `worker.serve` does.
  - `OFF_SLEEP_S = 60`, `MAX_BACKOFF_S = 30`. `main()` calls `db.init_pool(settings.database_url)` and then `serve()`.

- [ ] **Step 1: Failing tests.** The fixture `tg_lab` depends on `client` (its lifespan opens the pool). It sets a lab's slug as `settings.telegram_lab` and the token `"123:abc"`. `tg_call` is faked from a queue of results.

```python
def test_poll_stores_and_queues(tg_lab): ...
    # two private updates + one group -> two inbound_messages rows ("tg:123:<id>"), body_enc has no plaintext,
    # two msg.inbound jobs with payload == {"message_id": …, "channel": "telegram"}; returns max+1
def test_poll_dedupes(tg_lab): ...           # the same updates again (restart, no offset) -> no new row, no new job
def test_offset_passed_back(tg_lab): ...     # second getUpdates params carry offset == first return; allowed_updates ["message"]
def test_no_token_logs_once_and_sleeps(monkeypatch, caplog): ...
    # serve(iterations=3, sleep=fake): one "telegram off" record, sleeps [60, 60, 60], tg_call never called
def test_error_backs_off(tg_lab): ...        # tg_call raises TelegramError twice then [] -> sleeps [1, 2, …]
```

- [ ] **Step 2:** `uv run pytest tests/test_telegram_poll.py -q`. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the tests above, then `docker compose up -d --build telegram`. `docker compose logs telegram` shows the one "telegram off" line with no token set.
- [ ] **Step 5:** Commit `feat: telegram long-polling service`.

---

### Task 6: Telegram linking, commands, questions, media — TDD

**Files:**
- Modify: `backend/app/channels_api.py` (`channel: Literal["whatsapp", "telegram"]`), `chat_api.py` (`converse`'s `channel` Literal adds `"telegram"`), `msg_jobs.py` (`ADAPTERS["telegram"]`, `CONSENT_VERSION["telegram"] = "tg-2026-11-v1"`, `_account`, command dispatch through `adapter.command`), `privacy.py` (`Purpose` adds `telegram`; `/api/me` `consent` adds `"telegram": bool`)
- Test: `backend/tests/test_tg_inbound.py`, `backend/tests/test_privacy.py`

**Interfaces:**
- Consumes: Tasks 3–5.
- Produces:
  - The Telegram link routes (T11): `GET` → `{"available", "linked", "opted_in"}`; `POST` → 201 `{"url", "expires_in"}`.
  - `_account(c, tid, "telegram")`: `"telegram"` when the tenant's slug equals `settings.telegram_lab`, else None.
  - The shared handler calls `adapter.command(text)`. Its replies come from `adapter.COPY`, are split with `whatsapp.split(paras, adapter.CHUNK)`, and the link is stored with `channel`. The media report's source equals the channel.

- [ ] **Step 1: Failing tests.** Helpers:
  - `tg_deliver(client, tid, chat=42, text=None, document=None, photo=None, models=None)`: builds an update, calls `telegram_poll.store_update`, then `worker.run_once` until idle;
  - `tg_sent`: records `sendMessage` params;
  - `_tg_code(client)`: takes the code from the `url`.

```python
def test_tg_link_flow(client, patient, tg_lab, tg_sent): ...
    # url == f"https://t.me/prime_test_bot?start={code}", len(code) == 43, DB holds only code_hash;
    # "/start <code>" -> channel_links row channel 'telegram', consent 'telegram', reply COPY linked;
    # GET /api/channels/telegram/link -> linked, opted_in
def test_code_only_redeems_on_its_channel(client, patient, tg_lab, wa_lab, tg_sent, sent): ...  # Review Focus 4
    # a whatsapp code sent as "/start <code>" -> bad_code, no link; a telegram code as "LINK …" never matches
def test_tg_code_leaves_whatsapp_code_live(client, patient, tg_lab, wa_lab, sent): ...  # T10 supersede per channel
def test_tg_unavailable_409(client, patient): ...                          # slug != telegram_lab -> 409 telegram_unavailable
def test_tg_expired_or_used_code(...): ...
def test_tg_stop_start_and_silence(...): ...                               # /stop -> stopped; then /report -> nothing; /start -> started
def test_tg_report_sends_explanation(...): ...                             # chunks <= 4096 hold the statements, then ask_more
def test_tg_question_continues_one_history(client, patient, tg_lab, wa_lab, tg_sent, sent, model): ...
    # web, then WhatsApp, then Telegram on one report: the fake model sees the earlier turns;
    # GET /api/reports/{id}/chat channels == ["web","web","whatsapp","whatsapp","telegram","telegram"]
def test_tg_document_makes_report(...): ...                                # getFile + bytes -> source 'telegram', one pipeline job, 'reading'
def test_tg_photo_uses_largest(...): ...                                   # getFile called with the last size's file_id
def test_tg_oversize_or_bad_path_is_bad_file(...): ...                     # no report row
def test_tg_failed_send_retried(...): ...                                  # Review Focus 2: sendMessage raises once; retry delivers; one link
def test_tg_unlink_withdraws_only_telegram(...): ...                       # whatsapp consent untouched

# test_privacy.py
def test_telegram_consent_grant_and_withdraw(client, patient): ...         # /api/me consent == {"core", "whatsapp", "telegram"} keys
```

- [ ] **Step 2:** `uv run pytest tests/test_tg_inbound.py tests/test_privacy.py -q`. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run, then the full suite. Expected: PASS, WhatsApp tests unchanged.
- [ ] **Step 5:** Commit `feat: telegram linking, commands, questions and media`.

---

### Task 7: Telegram alerts — TDD

**Files:**
- Modify: `backend/app/msg_jobs.py` (`notify`)
- Test: `backend/tests/test_tg_notify.py`

**Interfaces:**
- Produces: `notify` for `channel == "telegram"` always sends free text (T16), after the same link, consent and report-exists checks:
  - `report_ready` → `split(report_paragraphs(detail, lang), telegram.CHUNK)` + `COPY["ask_more"]`;
  - `review_complete` / `trend_alert` → `telegram.COPY[event][lang].format(lab=tenants.name)`.
  WhatsApp keeps its window and template branch unchanged.

- [ ] **Step 1: Failing tests**

```python
def test_tg_ready_sends_explanation(...): ...
def test_tg_ready_red_urgent_first(...): ...           # Review Focus 3: parked red; first text starts with URGENT_EN, once
def test_tg_review_complete_and_trend_once(...): ...   # doctor approves -> review_complete text; 3rd rising HbA1c -> one trend text
def test_tg_stop_leaves_whatsapp_on(...): ...          # Review Focus 5: both linked; job queued; /stop on Telegram;
    # run jobs -> Telegram sends nothing, WhatsApp sends its message
def test_tg_notify_after_delete_me(...): ...           # nothing sent, jobs done
```

- [ ] **Step 2:** `uv run pytest tests/test_tg_notify.py -q`. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run, then the full suite and ruff. Expected: PASS.
- [ ] **Step 5:** Commit `feat: telegram report, review and trend alerts`.

---

### Task 8: Web — Telegram strip, call button, channel tag

**Files:**
- Create: `web/src/Telegram.tsx`, `web/src/channels.ts`, `web/src/channels.test.ts`
- Modify:
  - web: `web/src/api.ts`, `WhatsApp.tsx` (move to the generic API), `pages/Profile.tsx`, `Chat.tsx`, `pages/Report.tsx` and `pages/Dashboard.tsx` (call button), `i18n.tsx`;
  - backend: `backend/app/reports.py` (`lab_phone`, T3), `backend/app/seed.py` (`tenants.phone` for lab-alpha, `WHERE phone IS NULL`);
  - tests: `web/src/waLink.test.ts` and `waLink.ts` (unchanged unless imports move).
- Test: `web/src/channels.test.ts`; `backend/tests/test_visibility.py`

**Interfaces:**
- Consumes: the Task 3 and Task 6 routes; the `channel` key on chat history.
- Produces:
  - `api.channelLink(channel)`, `api.channelLinkCode(channel, language)`, `api.channelUnlink(channel)`, with `type Channel = "whatsapp" | "telegram"`. The old `waLink*` helpers are deleted.
  - `type TgLink = { available: boolean; linked: boolean; opted_in: boolean }`, `type TgLinkCode = { url: string; expires_in: number }`.
  - `ChatMessage.channel?: "web" | Channel`; `ReportDetail.lab_phone?: string | null`.
  - In `channels.ts`:
    - `telHref(phone?: string | null): string | null`: digits and a leading `+` only, so `"+91 11 4000-0000"` → `"tel:+911140000000"`; empty or null → null;
    - `viaKey(channel?: string): "viaWhatsApp" | "viaTelegram" | null`.

UI (impeccable, Clean Monochrome, the `strip` pattern):
- A "Telegram" strip on Profile under WhatsApp, patients only:
  - not available → one hint line;
  - not linked → a "Connect Telegram" button that posts for the code and then `window.location.assign(url)`; reload the status on `visibilitychange`, as `WhatsApp.tsx` does;
  - linked → "Connected", the opted-out hint when needed, and "Unlink".
- `UrgentBanner` gets a `<a className="btn" href={telHref(phone)}>` "Call your lab" when `telHref` is not null.
- Chat: the `chat__via` tag uses `viaKey`.
- EN + HI keys: `tgTitle`, `tgLede`, `tgUnavailable`, `tgConnect`, `tgLinked`, `tgOptedOut`, `tgUnlink`, `viaTelegram`, `callLab`. HI under the machine-drafted comment.

- [ ] **Step 1: Failing tests**

```ts
expect(telHref("+91 11 4000-0000")).toBe("tel:+911140000000");
expect(telHref("")).toBeNull(); expect(telHref(null)).toBeNull();
expect(viaKey("telegram")).toBe("viaTelegram"); expect(viaKey("web")).toBeNull(); expect(viaKey(undefined)).toBeNull();
```
```python
def test_red_detail_has_lab_phone(client, patient): ...  # tenants.phone set by owner SQL: red detail lab_phone == it; amber: key absent
```

- [ ] **Step 2:** `npx vitest run`; `uv run pytest tests/test_visibility.py -q`. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `npx vitest run; npx tsc -b; npm run lint; npm run build`, and the backend test. Expected: clean. `docker compose restart web`. On http://localhost:5173 as patient `+919000000001`: Profile shows both strips; "Connect Telegram" opens the `t.me` link; a red report shows "Call your lab".
- [ ] **Step 5:** Commit `feat: telegram strip, call-your-lab button, channel tag`.

---

### Task 9: Evals, dev tool, results, live check

**Files:**
- Create: `scripts/tg_fake.py`
- Modify: `evals/run.py` (`SUITES["telegram"]`), `.github/workflows/ci.yml` (add `telegram` after `whatsapp`), `evals/RESULTS.md`, `phases/phase-3.1-telegram.md` (tick the boxes)
- Test: the suite itself

**Interfaces:**
- `scripts/tg_fake.py --chat 1001 --text "/start <code>" | --pdf path`:
  - builds a private-chat update with a random `update_id`, then calls `telegram_poll.store_update(tid, update)` for the tenant with slug `TELEGRAM_LAB`, with no Telegram involved;
  - run from `backend/` with `DATABASE_URL=postgresql://hc_app:app_dev@localhost:5433/healthcare`;
  - replies show in `docker compose logs worker` (log-only send with no token). A `--pdf` needs a token, so it is for the live check only.
- `run_telegram() -> list[tuple[str, bool, str]]`, with these cases:
  - every fixture spec: `split(report_paragraphs(detail, lang), telegram.CHUNK)`, EN and HI, has every chunk ≤ 4096 and joins back to the paragraphs; it holds every statement and the closing line once; for red, `paras[0] == urgent_message(lang)` once;
  - every `telegram.COPY` text: EN + HI, no digit, no placeholder but `{lab}`.

- [ ] **Step 1:** Add the suite; run `uv run python ../evals/run.py telegram`. Expected: all pass. If one fails, fix the code, never the case.
- [ ] **Step 2:** Dev check without Telegram: `docker compose up -d --build api worker telegram`. Get a code in the app, take it from the URL, then run `uv run python ../scripts/tg_fake.py --chat 1001 --text "/start <code>"` and then `--text "/report"`. The worker log shows the linked reply and the explanation.
- [ ] **Step 3:** Live check (user, with the bot from "Before starting"):
  1. Run `curl "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/deleteWebhook"` once (`getUpdates` returns 409 while a webhook is set).
  2. `docker compose up -d --build telegram worker api`.
  3. On a phone: Profile → Connect Telegram → Start; then `/report`, a question, a PDF, `/stop`, then a new report (nothing should arrive).
- [ ] **Step 4:** Run the full checks:
  - the backend suite (`rtk proxy uv run pytest -q -m "not live"`, with the worker stopped) and ruff;
  - the web checks;
  - every offline eval suite (`smoke fixtures chat trends red whatsapp telegram`).
  Record the counts in `RESULTS.md`. Tick the spec's Done-when boxes that the tests and the live check prove.
- [ ] **Step 5:** Commit `test: telegram evals, dev update tool, results`.
- [ ] **Step 6:** Ask the user before running `security-review` and the final whole-branch review. The focus: token hygiene, the link codes, the media download, and the red release.
