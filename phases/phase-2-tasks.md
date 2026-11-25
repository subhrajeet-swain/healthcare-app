# Phase 2: Timeline and doctor-in-the-loop — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** every report a patient has becomes one history per test, trends are caught in code, and a doctor stands between risky findings (red reports, trend alerts, gated chat answers) and the patient. Families share one account with per-member consent, and a patient can share a read-only link with an outside doctor.

**Architecture:** The pipeline gains a `review` node that calls LangGraph `interrupt()` for red or untrusted reports. The worker stores the results, leaves the thread checkpointed and writes a `review_items` row. A doctor's decision, or a per-lab timeout, queues a `report.resume` job that continues the thread with `Command(resume=…)`. Canonical values (converted units) are written beside the printed values in `results` at store time, so the timeline is one indexed read. `detect_trends` is a pure function run after every store. Family access is a `X-Profile` header resolved once in `current_ctx`. Share links are hashed random tokens behind a public, audited endpoint.

**Tech Stack:** unchanged from phase 1 (FastAPI, psycopg 3, Postgres 16 RLS, LangGraph + Postgres checkpointer, React 19 + Vite). New: stdlib `smtplib` only. No chart library: inline SVG.

**Spec:** [phase-2-timeline-doctor.md](phase-2-timeline-doctor.md), with [PLAN.md](../PLAN.md) sections 3 and 5. Phase 1 plan for conventions: [phase-1-tasks.md](phase-1-tasks.md).

## Before starting (user actions)

1. Reset the dev database once, because Task 4 adds `NOT NULL` columns to `results`: `docker compose down -v` then `docker compose up`. Dev data is seed-only.
2. Optional, for real doctor email: set `SMTP_URL` (for example `smtp://user:app-password@smtp.gmail.com:587`) and `APP_BASE_URL` in `.env`. Without them the alert is logged, not sent, and every test still passes.
3. Branch `phase-2` from `phase-1.1` (PR #3 not merged yet; rebase onto `main` after it merges).

## Rulings made while planning (review these)

| # | Decision | Why | Cost if wrong |
|---|---|---|---|
| Q1 | The synonym table is `brain/data/tests.json` (~50 tests): id, display name, canonical unit, synonyms. `VOCABULARY` and `CANONICAL` are generated from it. `canonicalise` maps an unknown `test_id` through the synonyms of the printed `test_name` before dropping it | Phase 1 already gives the model a vocabulary; the table makes it one file and catches the model's near-misses ("Glycated Haemoglobin") in code | none; LOINC later replaces ids, not the mechanism |
| Q2 | `results` keeps the printed value and unit and gains `value_c`, `ref_low_c`, `ref_high_c`, `unit_c`, `excluded_reason`, plus `user_id` and `observed_on` | The report is the authority; conversion is our claim and stays beside it. Denormalised `user_id`/`observed_on` make the timeline one indexed query (spec) | two more columns kept in sync by `store_result` only |
| Q3 | `observed_on = coalesce(collected_on, created_at::date)` | `collected_on` is null on many reports (phase 1 ruling: never guess a date) | upload date can lag the sample by days; acceptable for trends |
| Q4 | Trend rule: last 3 convertible points; every step in one direction; total change ≥ 10% of the latest range width; alert only when moving away from the range midpoint and the last point is out of range or within 10% of the edge, or past halfway from the edge to a critical limit. Ranges are each point's own (converted) range | Spec: relative to each lab's range. Small, explainable, table-tested | thresholds are not clinically validated (spec risk); a clinician must check before real use |
| Q5 | Every review waits in the graph via `interrupt()` (spec). The API never touches the checkpointer: decisions and timeouts become `report.resume` jobs the worker runs | The API has no graph connection (compose sets `GRAPH_DATABASE_URL: ""` for it) and the worker already owns resume logic | resume latency is the 1 s poll |
| Q6 | Reports that interrupt: red, or any warnings (phase 1 P4). Only **red** is hidden from the patient while pending; a warnings-only report shows its values with an "under review" note | Spec hides red; hiding every unit warning would hide many amber reports for no safety gain | patient sees an unverified amber report, as in phase 1 |
| Q7 | Doctor actions: `approve`, `edit` (pick one of `NOTE_OPTIONS`), `escalate`. Timeout = `escalate` with no doctor. Escalation releases the report with the urgent template plus "Please call your lab today" and emails the lab | Spec: fixed options; a red result must reach the patient eventually rather than sit hidden | none |
| Q8 | `NOTE_OPTIONS = ["repeat_test", "see_doctor_soon", "no_action_needed", "call_lab"]`, copy in `templates.py` EN + HI | Fixed text means no free-typed doctor notes to gate | doctors may want free text later |
| Q9 | Doctor email goes to one address per lab: `tenant_settings.settings.doctor_email`. The mail holds no patient data: "A report needs review" + the queue link | Users have no email column; a lab pathologist inbox is the real-world shape | multiple doctors share one inbox |
| Q10 | Per-lab settings read the latest `tenant_settings` version: `review_timeout_minutes` (default 240), `doctor_email` (default none) | Table exists since phase 0, versioned | none |
| Q11 | Dependants without a phone (`relation = 'child'`) are patient users with `phone_fp`/`phone_enc` NULL, linked `active` at once, consent `granted_by` the manager. Adults are invited by phone and the link stays `pending` until they accept while signed in | Spec: adults accept; children cannot | an adult dependant with no phone cannot be added (use `child` is wrong for them; deferred) |
| Q12 | Acting for a member: header `X-Profile: <member user id>`. `current_ctx` swaps `user_id` to the member and keeps the signed-in user as `actor_id`, after checking an `active` link. Audit records `actor_id or user_id` | One check every route inherits; no per-route family code | a route that must stay personal needs `own_only` (listed in Task 11) |
| Q13 | Share link URL `/s/{slug}/{token}`; token 32 random bytes, stored as SHA-256; expiry 1 h to 7 days, default 24 h; revocable; only reports not pending red review; no file, no chat | Slug gives the tenant without a session; hash means a DB leak leaks no links | none |
| Q14 | Chat answers the gate replaced (`ChatReply.gated`) create a `chat` review item. The doctor approves (the fixed reply stands) or edits (a `NOTE_OPTIONS` line is appended as an assistant message, tier `doctor`). No hiding | Spec: gated answers go to the queue; the fixed reply is already safe | none |
| Q15 | Charts are inline SVG from a pure `scale()` function (phase 1 P12 stands) | One chart shape; no dependency | none |

## Global Constraints

- Everything in phase 1's Global Constraints still holds (tenant tables with RLS forced and composite FKs, `ApiError`, same 404 for missing and forbidden, audit on every patient read, no network in tests, the model never decides anything clinical, no AI attribution in commits, commit as `subhrajeet.diaz@gmail.com`).
- New statuses: none. Review item statuses (exact): `pending`, `approved`, `edited`, `escalated`. Kinds: `report`, `trend`, `chat`. Reasons: `red`, `warnings`, `trend`, `gated_answer`.
- Trend directions: `rising`, `falling`. Toward: `out_of_range`, `critical`. Trend colour is always `amber`.
- Job kinds (exact): `report.pipeline` (exists), `report.resume`, `review.timeout`, `alert.email`.
- Doctor routes live under `/api/doctor` and return 404 to every other role (dependency, as `staff._staff`).
- Hindi copy is machine-drafted; mark it with the same comment as `Consent.tsx`.
- After every web edit: `docker compose restart web` from the repo root (no hot reload).
- UI work uses `impeccable` in the Clean Monochrome world (DESIGN.md). Never re-propose Chemist Strip.

## Review Focus

1. **A red report leaks while pending** through any door: list, detail, SSE snapshot, chat, timeline, share link, family member view, export. Expected: no red value, flag or explanation anywhere. Tests: Task 7 `test_red_pending_hidden_everywhere`, Task 10 `test_timeline_skips_pending_red`, Task 12 `test_share_excludes_pending_red`.
2. **Doctor decides just after the timeout fired** (or two doctors click at once). Expected: exactly one resume; the loser gets 409 `already_decided`. Tests: Task 6 `test_timeout_skips_decided_item`, Task 8 `test_second_decision_is_409`.
3. **The same report is stored twice** (retry after a failed save, or resume). Expected: one trend row, one review item. Test: Task 5 `test_restore_is_idempotent`.
4. **Delete-my-data while a review is pending.** Expected: checkpoint thread, review items, trends and share links all gone; a later `report.resume` job is dropped. Test: Task 6 `test_delete_me_with_pending_review`.
5. **A family link is revoked while the manager has the member's profile open.** Expected: the very next request with that `X-Profile` gets 404. Test: Task 11 `test_revoked_link_404_immediately`.

---

### Task 1: Test catalogue and synonym table (TDD)

**Files:**
- Create: `backend/app/brain/data/tests.json`, `backend/app/brain/catalogue.py`
- Modify: `backend/app/brain/extract.py` (build `VOCABULARY`/`CANONICAL` from the catalogue; synonym fallback in `canonicalise`), `.gitignore`
- Test: `backend/tests/brain/test_catalogue.py`, `backend/tests/brain/test_extract.py`

**Interfaces:**
- Produces: `catalogue.TESTS: dict[str, TestDef]` where `TestDef = TypedDict("TestDef", {"name": str, "unit": str, "synonyms": list[str]})`; `catalogue.lookup(name: str) -> str | None` (normalised name or synonym to test id); `extract.VOCABULARY`, `extract.CANONICAL` unchanged in shape.

- [ ] **Step 1:** Add `backend/data/` to `.gitignore` under `/data/` (the default `storage_dir` is `data/files` relative to `backend/`; the old bare `data/` rule hid it, the anchored one does not).
- [ ] **Step 2: Failing tests**

```python
def test_catalogue_keeps_every_phase1_id():
    assert set(json.loads(CRITICAL_JSON.read_text("utf-8"))) <= set(TESTS)

def test_catalogue_size(): assert 45 <= len(TESTS) <= 60

@pytest.mark.parametrize("printed,tid", [
    ("Glycated Haemoglobin", "hba1c.hba1c"), ("HbA1c", "hba1c.hba1c"),
    ("glycosylated hemoglobin (HbA1c)", "hba1c.hba1c"), ("FBS", "glucose.fasting"),
    ("Fasting Blood Sugar", "glucose.fasting"), ("S. Creatinine", "kft.creatinine"),
    ("SGPT", "lft.alt"), ("Unknown Thing", None)])
def test_lookup(printed, tid): assert lookup(printed) == tid

def test_no_synonym_maps_to_two_ids():
    seen = {}
    for tid, d in TESTS.items():
        for s in [d["name"], *d["synonyms"]]:
            assert seen.setdefault(_norm(s), tid) == tid

def test_canonicalise_rescues_by_name():  # in test_extract.py
    rep = _extracted(("hba1c", "Glycated Haemoglobin", 6.5, "%"))
    out, warnings = canonicalise(rep)
    assert out.results[0].test_id == "hba1c.hba1c" and warnings == []
```

- [ ] **Step 3:** Run `cd backend && uv run pytest tests/brain/test_catalogue.py tests/brain/test_extract.py -q`. Expected: FAIL (no module `catalogue`).
- [ ] **Step 4:** Write `tests.json`: the 19 phase-1 ids plus `glucose.fasting`, `glucose.pp`, `glucose.random`, `kft.creatinine`, `kft.urea`, `kft.bun`, `kft.uric_acid`, `kft.egfr`, `electrolytes.sodium`, `electrolytes.potassium`, `electrolytes.chloride`, `minerals.calcium`, `vitamins.d`, `vitamins.b12`, `iron.ferritin`, `iron.serum_iron`, `inflammation.esr`, `inflammation.crp`, `lipid.vldl`, `lipid.non_hdl`, `thyroid.ft3`, `thyroid.ft4`, `lft.ggt`, `lft.total_protein`, `lft.globulin`, `lft.bilirubin_direct`, `cbc.mch`, `cbc.mchc`, `cbc.rdw`, `cbc.neutrophils`, `cbc.lymphocytes`. Units are the usual Indian-lab units. `_norm(s)` lower-cases, folds `µ/μ` to `u`, drops punctuation and spaces. `lookup` also tries the text inside brackets. `extract.VOCABULARY` is generated in the same column layout it has today. `canonicalise` tries `lookup(r.test_name)` when `r.test_id` is unknown, then drops as before.
- [ ] **Step 5:** `uv run pytest -q -m "not live" && uv run ruff check . ../evals ../scripts`. Expected: PASS, including `evals/run.py fixtures` 15/15 unchanged.
- [ ] **Step 6:** Commit `feat: test catalogue with synonyms; canonicalise rescues tests by printed name`.

### Task 2: Unit conversion (TDD, table-driven)

**Files:**
- Create: `backend/app/brain/units.py`
- Test: `backend/tests/brain/test_convert.py`

**Interfaces:**
- Consumes: `catalogue.TESTS` (canonical unit), `flags._norm_unit` (alias folding; make it public as `norm_unit`).
- Produces: `to_canonical(test_id: str, value: float, unit: str) -> float | None` and `Converted = NamedTuple(value, ref_low, ref_high, unit)`; `convert(r: TestResult) -> Converted | None` (None means not convertible).

- [ ] **Step 1: Failing tests**

```python
@pytest.mark.parametrize("tid,value,unit,expected", [
    ("glucose.fasting", 5.5, "mmol/L", 99.1),        # x 18.016
    ("glucose.fasting", 99, "mg/dL", 99),            # already canonical
    ("lipid.total_cholesterol", 5.2, "mmol/L", 201.1),  # x 38.67
    ("lipid.triglycerides", 1.7, "mmol/L", 150.6),   # x 88.57
    ("kft.creatinine", 88.4, "umol/L", 1.0),         # / 88.4
    ("lft.bilirubin_total", 17.1, "µmol/L", 1.0),    # / 17.1
    ("cbc.hemoglobin", 135, "g/L", 13.5),            # / 10
    ("hba1c.hba1c", 48, "mmol/mol", 6.5),            # % = 0.09148 * IFCC + 2.152
    ("vitamins.d", 50, "nmol/L", 20.0),              # / 2.496
    ("cbc.wbc", 7.8, "thou/cumm", None),             # scale not in the table
    ("glucose.fasting", 99, "banana", None)])
def test_to_canonical(tid, value, unit, expected):
    got = to_canonical(tid, value, unit)
    assert got == expected if expected is None else got == pytest.approx(expected, abs=0.1)

def test_convert_moves_the_range_too():
    c = convert(_result("glucose.fasting", 5.5, "mmol/L", ref=(3.9, 5.5)))
    assert (c.unit, round(c.ref_low), round(c.ref_high)) == ("mg/dL", 70, 99)

def test_convert_keeps_one_sided_range():
    c = convert(_result("lipid.ldl", 2.6, "mmol/L", ref=(None, 2.6)))
    assert c.ref_low is None and c.ref_high == pytest.approx(100.5, abs=0.1)
```

- [ ] **Step 2:** Run `uv run pytest tests/brain/test_convert.py -q`. Expected: FAIL.
- [ ] **Step 3:** Implement `_FACTORS: dict[tuple[str, str], tuple[float, float]]` keyed `(test_id or prefix, norm_unit)`, giving `(multiply, add)` into the canonical unit. Same normalised unit returns the value unchanged. The HbA1c IFCC row is affine (`0.09148, 2.152`); every other row has `add = 0`. Prefix keys (`"lipid"` for every cholesterol fraction) keep the table short.
- [ ] **Step 4:** Run the test. Expected: PASS.
- [ ] **Step 5:** Commit `feat: unit conversion into canonical units, ranges included`.

### Task 3: `detect_trends` (TDD, table-driven)

**Files:**
- Create: `backend/app/brain/trends.py`
- Test: `backend/tests/brain/test_trends.py`

**Interfaces:**
- Produces: `Point = NamedTuple(report_id: str, observed_on: date, value: float, ref_low: float | None, ref_high: float | None)`; `Trend` (dataclass: `test_id`, `direction: Literal["rising","falling"]`, `toward: Literal["out_of_range","critical"]`, `first_value`, `last_value`, `points: int`, `last_report_id`); `detect_trends(series: dict[str, list[Point]]) -> list[Trend]`. `CRITICAL` limits come from `critical.json` in canonical units.

- [ ] **Step 1: Failing tests** (one table, each row a series and the expected trend or `None`)

```python
CASES = [
    ("hba1c rising out of range", "hba1c.hba1c", [(6.1, 4.0, 5.6), (6.5, 4.0, 5.6), (7.0, 4.0, 5.6)], ("rising", "out_of_range")),
    ("two points is not a trend", "hba1c.hba1c", [(6.1, 4.0, 5.6), (7.0, 4.0, 5.6)], None),
    ("zig-zag", "hba1c.hba1c", [(6.1, 4.0, 5.6), (6.8, 4.0, 5.6), (6.5, 4.0, 5.6)], None),
    ("rising inside the range, far from the edge", "lipid.hdl", [(45, 40, None), (50, 40, None), (55, 40, None)], None),
    ("rising toward the middle is recovery", "cbc.hemoglobin", [(10, 13, 17), (11.5, 13, 17), (12.8, 13, 17)], None),
    ("falling hb toward critical 7", "cbc.hemoglobin", [(11, 13, 17), (10, 13, 17), (9.5, 13, 17)], ("falling", "critical")),
    ("change under 10% of range width", "glucose.fasting", [(96, 70, 100), (97, 70, 100), (98, 70, 100)], None),
    ("labs with different ranges compared on position", "lft.alt", [(30, 0, 40), (38, 0, 45), (52, 0, 50)], ("rising", "out_of_range")),
    ("only last three count", "hba1c.hba1c", [(7.5, 4, 5.6), (6.1, 4, 5.6), (6.5, 4, 5.6), (7.0, 4, 5.6)], ("rising", "out_of_range")),
    ("no range at all", "inflammation.esr", [(10, None, None), (20, None, None), (30, None, None)], None),
]
@pytest.mark.parametrize("name,tid,rows,want", CASES, ids=[c[0] for c in CASES])
def test_detect_trends(name, tid, rows, want): ...  # builds Points a month apart; asserts (t.direction, t.toward) or []

def test_points_sorted_by_date_not_input_order(): ...
def test_same_day_points_keep_last_report(): ...
```

- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement per ruling Q4. Position of a point: two-sided `(v - low) / (high - low)`; one-sided uses the single bound as the edge and `|bound| * 0.5` as the width. No bound at all means no trend for that test. "Away from the midpoint" is direction rising with the last position > 0.5, or falling with < 0.5. Module docstring says the thresholds need a clinician's check (spec risk).
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5:** Commit `feat: detect_trends, rules relative to each lab's range`.

### Task 4: Schema for phase 2

**Files:**
- Create: `backend/app/migrations/005_phase2.sql`
- Test: `backend/tests/test_schema.py`, `backend/tests/test_canary.py`

**Interfaces:**
- Produces tables and columns used by every later task:
  - `results` + `user_id uuid NOT NULL`, `observed_on date NOT NULL`, `value_c double precision`, `ref_low_c`, `ref_high_c`, `unit_c text`, `excluded_reason text`; index `results_timeline (tenant_id, user_id, test_id, observed_on)`; FK `(tenant_id, user_id) → users ON DELETE CASCADE`.
  - `trends (id, tenant_id, user_id, test_id, direction, toward, first_value, last_value, unit_c, points int, last_report_id, created_at)`, `UNIQUE (user_id, test_id, last_report_id)`, FKs to users and reports cascade.
  - `review_items (id, tenant_id, kind, reason, user_id, report_id NULL, trend_id NULL, chat_message_id NULL, thread_id NULL, status DEFAULT 'pending', note_option NULL, decided_by NULL, decided_at NULL, due_at NOT NULL, created_at)` with the CHECKs from Global Constraints; partial unique index `review_one_pending_report ON review_items (report_id) WHERE kind = 'report' AND status = 'pending'`; unique `(trend_id)` and `(chat_message_id)`.
  - `family_links (id, tenant_id, manager_id, member_id, relation CHECK IN ('child','parent','spouse','other'), status CHECK IN ('pending','active','revoked'), created_at, accepted_at)`, `UNIQUE (tenant_id, manager_id, member_id)`, `CHECK (manager_id <> member_id)`.
  - `share_links (id, tenant_id, user_id, created_by, token_hash bytea UNIQUE NOT NULL, report_ids uuid[] NOT NULL, expires_at, revoked_at NULL, created_at)`.
  - `users.phone_fp`, `users.phone_enc` drop NOT NULL, plus `CHECK (phone_fp IS NOT NULL OR role = 'patient')`; `consents.granted_by uuid NULL`.
  - The phase-1 RLS loop (copy it), then `GRANT SELECT, INSERT, UPDATE, DELETE` on the four new tables to `hc_app`.

- [ ] **Step 1: Failing tests**

```python
def test_phase2_tables_have_forced_rls(owner):  # extends the phase-0 check
    for t in ["trends", "review_items", "family_links", "share_links"]:
        assert _rls_forced(owner, t)

def test_one_pending_review_per_report(owner_tenant_tx, report):
    _insert_review(report, "pending")
    with pytest.raises(psycopg.errors.UniqueViolation):
        _insert_review(report, "pending")

def test_staff_must_have_phone(owner_tenant_tx):
    with pytest.raises(psycopg.errors.CheckViolation):
        _insert_user(role="doctor", phone_fp=None)
```

  Add `trends`, `review_items`, `family_links`, `share_links` to the canary test's table list (lab B sees none of lab A's rows).
- [ ] **Step 2:** Run `uv run pytest tests/test_schema.py tests/test_canary.py -q`. Expected: FAIL.
- [ ] **Step 3:** Write the migration. Run the user action "reset the dev database".
- [ ] **Step 4:** Run the full backend suite. Expected: PASS (existing inserts into `results` fail until Task 5; keep this commit green by giving `store_result` the two new columns here: `user_id` from the report row, `observed_on` per Q3).
- [ ] **Step 5:** Commit `feat: phase 2 schema (trends, review items, family links, share links)`.

### Task 5: Store canonical values and trends

**Files:**
- Modify: `backend/app/reports.py` (`store_result`)
- Create: `backend/app/review.py` (`refresh_trends`, `open_review`)
- Modify: `backend/app/db.py` (`tenant_setting`)
- Test: `backend/tests/test_trends_store.py`

**Interfaces:**
- Consumes: `units.convert`, `trends.detect_trends`, `trends.Point`.
- Produces: `db.tenant_setting(c, key: str, default: Any) -> Any` (latest version's `settings ->> key`); `review.refresh_trends(c, tenant_id: UUID, user_id: UUID) -> list[UUID]` (new trend ids); `review.open_review(c, tenant_id, *, kind, reason, user_id, report_id=None, trend_id=None, chat_message_id=None, thread_id=None) -> UUID | None` (None if an equal item exists; also queues `review.timeout` at `due_at` and `alert.email`). `REVIEW_TIMEOUT_DEFAULT_MIN = 240`.

- [ ] **Step 1: Failing tests** (DB, through `store_result` with `template_result` reports)

```python
def test_three_hba1c_reports_make_one_amber_trend_and_review(lab_patient):
    for v, day in [(6.1, "2026-01-10"), (6.5, "2026-04-10"), (7.0, "2026-07-10")]:
        _store(lab_patient, hba1c=v, collected_on=day)
    trend = _one("SELECT * FROM trends")
    assert (trend["direction"], trend["toward"], trend["points"]) == ("rising", "out_of_range", 3)
    assert _one("SELECT reason, status FROM review_items WHERE kind = 'trend'") == {"reason": "trend", "status": "pending"}

def test_mixed_units_trend_in_mg_dl(lab_patient):
    for v, u in [(5.6, "mmol/L"), (110, "mg/dL"), (6.8, "mmol/L")]:  # 101, 110, 122.5 mg/dL; ref 70-100
        _store(lab_patient, glucose=(v, u))
    assert _one("SELECT direction FROM trends")["direction"] == "rising"

def test_unconvertible_point_is_excluded_with_reason(lab_patient):
    _store(lab_patient, wbc=(7.8, "thou/cumm"))
    row = _one("SELECT value_c, excluded_reason FROM results WHERE test_id = 'cbc.wbc'")
    assert row["value_c"] is None and row["excluded_reason"] == "unit_not_comparable"

def test_restore_is_idempotent(lab_patient):  # Review Focus 3
    rid = _store_three_hba1c(lab_patient)
    _restore(lab_patient, rid)
    assert _count("trends") == 1 and _count("review_items") == 1

def test_tenant_setting_reads_latest_version(lab): ...
```

- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** In `store_result`, fill the canonical columns from `convert(r)` (`excluded_reason = "unit_not_comparable"` when None), then call `refresh_trends(c, tenant_id, user_id)` and `open_review(kind="trend", reason="trend", trend_id=…)` for each new trend. `refresh_trends` reads the user's results in one query on `results_timeline`, skips points with `excluded_reason`, inserts with `ON CONFLICT DO NOTHING RETURNING id`.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5:** Commit `feat: canonical values and trend alerts written at store time`.

### Task 6: Review node, resume and timeout in the worker

**Files:**
- Modify: `backend/app/brain/pipeline.py` (`review` node, `PipelineResult.pending`, `resume()`), `backend/app/worker.py` (job dispatch, keep interrupted threads, `report.resume`, `review.timeout`, `alert.email`), `backend/app/privacy.py` (`delete_me` also deletes threads of pending reviews), `backend/app/config.py` (`smtp_url`, `app_base_url`)
- Create: `backend/app/alerts.py`
- Test: `backend/tests/brain/test_pipeline.py`, `backend/tests/test_review_flow.py`

**Interfaces:**
- Consumes: `review.open_review`, `db.tenant_setting`.
- Produces: `Decision = TypedDict(action: Literal["approve","edit","escalate"], option: str | None, by: str | None)`; `pipeline.resume(graph, thread: str, decision: Decision) -> PipelineResult`; `PipelineResult.pending: bool` and `.decision: Decision | None`; `alerts.send_review_alert(to: str, link: str) -> None` (logs when `smtp_url` is empty); worker `HANDLERS: dict[str, Callable[[dict, dict | None, Any], None]]` keyed by job kind.

- [ ] **Step 1: Failing tests**

```python
def test_red_report_interrupts_at_review(graph_with_fakes):          # test_pipeline.py
    res = run(graph_with_fakes(red=True), "t1")
    assert res.pending and res.final_status == "needs_review"

def test_green_report_does_not_interrupt(graph_with_fakes):
    assert not run(graph_with_fakes(red=False), "t2").pending

def test_resume_approve_finishes_ready_without_model_calls(graph_with_fakes):
    g = graph_with_fakes(red=True); run(g, "t3")
    res = resume(g, "t3", {"action": "approve", "option": None, "by": "doc"})
    assert (res.pending, res.final_status) == (False, "ready") and FakeModel.calls == 2  # extract + explain, once

def test_red_upload_parks_thread_and_opens_review(worker_env):        # test_review_flow.py
    rid = _upload_red(worker_env); run_once(FAKES)
    assert _status(rid) == "needs_review" and _thread_exists(rid)
    item = _review_for(rid)
    assert (item["reason"], item["status"]) == ("red", "pending")
    assert _jobs("review.timeout")[0]["run_after"] == item["due_at"]

def test_timeout_escalates(worker_env): ...      # run review.timeout job: status ready, item escalated, decided_by NULL, alert.email queued
def test_timeout_skips_decided_item(worker_env): ...   # Review Focus 2: item approved first; job ends done, no second resume
def test_resume_for_deleted_report_is_dropped(worker_env): ...
def test_delete_me_with_pending_review(worker_env): ...  # Review Focus 4: thread, review_items, trends, share_links gone
def test_alert_without_smtp_logs_only(caplog): ...
```

- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Pipeline: add `review` after `triage`. It returns `{"decision": None}` for green/amber without warnings; otherwise `interrupt({"triage": …})` and returns `{"decision": <resume value>}`. `run()` sees a pending interrupt as `graph.get_state(config).next == ("review",)` and returns `pending=True`. `resume()` invokes `Command(resume=decision)`. `final_status` is `ready` after any decision. Worker: `run_once` dispatches on `job["kind"]`. For a pending result it saves, calls `open_review(kind="report", reason="red" if triage == "red" else "warnings", thread_id=…)` and **does not** delete the thread. `report.resume` loads the item `FOR UPDATE`, requires `status` to be set by the API (Task 8), then resumes and saves. `review.timeout` locks the item; if still `pending` it sets `escalated`, then resumes with `{"action": "escalate", "by": None}`. `alert.email` reads `doctor_email`; none means done.
- [ ] **Step 4:** Run `uv run pytest -q -m "not live"`. Expected: PASS, including every phase-1 worker test.
- [ ] **Step 5:** Commit `feat: doctor review through interrupt(); resume and timeout jobs`.

### Task 7: The patient sees nothing red before review

**Files:**
- Modify: `backend/app/reports.py` (`report_detail`, `list_reports`, `_snapshot`), `backend/app/chat_api.py`, `backend/app/privacy.py` (`export`), `backend/app/brain/templates.py` (`NOTE_OPTIONS` copy, `CALL_LAB` line)
- Create: `backend/app/visibility.py`
- Test: `backend/tests/test_visibility.py`

**Interfaces:**
- Produces: `visibility.held(report: dict, pending: bool) -> bool` (True when `triage == "red"` and a report review is pending); `visibility.patient_view(detail: dict, held: bool) -> dict` (held: `status` `"under_review"`, `triage`, `results`, `explanations`, `urgent`, `next_step` removed); `review.pending_report_ids(c, user_id) -> set[UUID]`. Escalated/edited reports carry `doctor_note: {option, text: {en, hi}}` in the detail.

- [ ] **Step 1: Failing tests**

```python
def test_red_pending_hidden_everywhere(patient_with_pending_red):  # Review Focus 1
    rid = patient_with_pending_red
    detail = client.get(f"/api/reports/{rid}").json()
    assert detail["status"] == "under_review" and "results" not in detail and "triage" not in detail
    assert _listed(rid)["status"] == "under_review" and _listed(rid)["triage"] is None
    assert _first_sse_event(rid)["status"] == "under_review"
    assert client.post(f"/api/reports/{rid}/chat", json=_q()).status_code == 409   # error "under_review"
    assert "critical" not in json.dumps(client.get("/api/me/export").json())

def test_staff_and_doctor_still_see_values(...): ...
def test_warnings_only_report_shows_values_with_note(...): ...   # ruling Q6
def test_approved_report_released(...): ...
def test_escalated_report_shows_urgent_and_call_lab(...): ...
def test_gated_chat_answer_opens_review(...): ...                 # ruling Q14
```

- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement. Every patient-facing read goes through `patient_view`; staff roles bypass it. Chat on a held report raises `ApiError(409, "under_review")`. In `chat_api.chat`, a reply with `gated=True` calls `open_review(kind="chat", reason="gated_answer", chat_message_id=…)`.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5:** Commit `feat: red results held from the patient until review`.

### Task 8: Doctor API

**Files:**
- Create: `backend/app/doctor.py`; modify `backend/app/main.py` (router)
- Test: `backend/tests/test_doctor.py`

**Interfaces:**
- Consumes: `review_items`, `reports.report_detail`, `NOTE_OPTIONS`.
- Produces: `GET /api/doctor/queue` → `[{id, kind, reason, created_at, due_at, patient_name, report_id, trend: {...} | null, chat: {question, reply} | null}]`, pending only, oldest `due_at` first. `GET /api/doctor/reviews/{id}` → item plus full `report_detail` (staff view). `POST /api/doctor/reviews/{id}` body `{action: "approve"|"edit"|"escalate", option: NOTE_OPTIONS | null}` → `{status}`.

- [ ] **Step 1: Failing tests**

```python
def test_queue_is_doctor_only(client, login):
    for role in ["patient", "lab_staff", "lab_admin"]:
        login(role); assert client.get("/api/doctor/queue").status_code == 404

def test_edit_requires_a_known_option(doctor):
    assert doctor.post(f"/api/doctor/reviews/{iid}", json={"action": "edit", "option": "free text"}).status_code == 422

def test_approve_queues_resume(doctor, pending_red):
    assert doctor.post(..., json={"action": "approve", "option": None}).json() == {"status": "approved"}
    assert _jobs("report.resume")[0]["payload"] == {"review_item_id": str(iid)}

def test_second_decision_is_409(doctor, pending_red): ...   # Review Focus 2: {"error": "already_decided"}
def test_other_labs_item_is_404(doctor_lab_b, pending_red_lab_a): ...
def test_trend_and_chat_items_finish_without_a_job(doctor, ...): ...   # no graph thread to resume
def test_every_read_and_decision_audited(doctor, ...): ...
```

- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement with a `_doctor` dependency like `staff._staff`. The decision does `UPDATE review_items SET status, note_option, decided_by, decided_at WHERE id = %s AND status = 'pending' RETURNING …`; no row means 409. Report items then queue `report.resume`. An edited chat item inserts the option text as an assistant `chat_messages` row, tier `doctor`.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5:** Commit `feat: doctor review queue API`.

### Task 9: Doctor queue UI (`impeccable`)

**Files:**
- Create: `web/src/pages/Doctor.tsx`, `web/src/review.ts`, `web/src/review.test.ts`
- Modify: `web/src/api.ts`, `web/src/App.tsx` (doctor home), `web/src/i18n.tsx`, `web/src/styles/app.css`

**Interfaces:**
- Consumes: Task 8 endpoints.
- Produces: `review.ts`: `dueLabel(dueAt: string, now: Date) -> string` ("due in 2 h", "overdue 15 min"); `reasonWord(reason) -> string`; `api.doctorQueue()`, `api.doctorReview(id)`, `api.decide(id, action, option)`.

- [ ] **Step 1:** Failing vitest for `dueLabel` (future, past, under a minute) and `reasonWord` (all four reasons). Run `npx vitest run src/review.test.ts`. Expected: FAIL.
- [ ] **Step 2:** Implement `review.ts`. Run. Expected: PASS.
- [ ] **Step 3:** Run `impeccable` for the queue (list of white cards: reason word + colour word, patient, due label) and the review screen (report values, three actions; edit opens the four fixed notes as pills). Clean Monochrome only; a state colour always comes with a word.
- [ ] **Step 4:** `npx vitest run; npx tsc -b; npm run lint; npm run build`, then `docker compose restart web` from the repo root and check it as doctor `+919000000102`. Expected: all green; a seeded red report shows in the queue and approve releases it.
- [ ] **Step 5:** Commit `feat: doctor review queue screens`.

### Task 10: Timeline API and chart

**Files:**
- Create: `backend/app/timeline.py`; `web/src/pages/Timeline.tsx`, `web/src/chart.ts`, `web/src/chart.test.ts`
- Modify: `backend/app/main.py`, `web/src/routes.ts` (`/timeline`), `web/src/Nav.tsx` (Trends tab), `web/src/api.ts`, `web/src/i18n.tsx`
- Test: `backend/tests/test_timeline.py`

**Interfaces:**
- Produces: `GET /api/timeline` → `[{test_id, test_name, unit, points: [{report_id, observed_on, value, ref_low, ref_high}], excluded: [{report_id, observed_on, unit, reason}], trend: {direction, toward, review_status} | null}]`, tests with at least one point, ordered by test name. `chart.ts`: `scale(points, width: number, height: number) -> {dots: {x, y}[], band: {y, h} | null, yTicks: number[]}` (band = the latest point's range).

- [ ] **Step 1: Failing tests**

```python
def test_timeline_series_in_canonical_units(patient_with_three_glucose): ...
def test_excluded_point_listed_with_reason(...): assert excluded == [{"report_id": ..., "unit": "thou/cumm", "reason": "unit_not_comparable", ...}]
def test_timeline_skips_pending_red(...): ...           # Review Focus 1
def test_timeline_is_one_query(...): ...                # count statements via a psycopg cursor wrapper: 1 select on results
def test_timeline_audited(...): ...
```

  Vitest: `scale` maps min and max to the edges with padding, one point centres, no range gives `band: null`.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement. The chart is inline SVG: band rect, line, dots, last value labelled; amber word "Rising" or "Falling" on trend tests, with "Under review" while its item is pending. Excluded points show as a line of text under the chart: "One result (in thou/cumm) can't be compared with the others, so it's left out." Use `impeccable` for the page.
- [ ] **Step 4:** Backend suite, web checks, `docker compose restart web`, look at it as the seed patient. Expected: green.
- [ ] **Step 5:** Commit `feat: timeline with one chart per test`.

### Task 11: Family profiles with consent

**Files:**
- Create: `backend/app/family.py`; `web/src/Family.tsx`
- Modify: `backend/app/tenancy.py` (`actor_id`), `backend/app/auth.py` (`current_ctx` reads `X-Profile`), `backend/app/audit.py`, `backend/app/privacy.py` (`own_only` on delete, export, consents), `web/src/api.ts` (send `X-Profile`), `web/src/Band.tsx` (profile switcher), `web/src/pages/Profile.tsx`
- Test: `backend/tests/test_family.py`

**Interfaces:**
- Produces: `TenantCtx.actor_id: UUID | None = None`; `auth.own_only` dependency (404 when `ctx.actor_id`); `POST /api/family` `{relation, name, phone?}` (child: no phone, active now, consent `granted_by` manager; others: phone required, `pending`); `GET /api/family` → `{members: [...], invites: [...]}`; `POST /api/family/{link_id}/accept` (member only); `DELETE /api/family/{link_id}` (either side, sets `revoked`).

- [ ] **Step 1: Failing tests**

```python
def test_child_profile_usable_at_once(manager): ...
def test_adult_invite_pending_until_accepted(manager, adult): # X-Profile 404 before accept, 200 after
def test_member_without_consent_cannot_upload(...): ...      # 403 consent_required, same as a patient
def test_revoked_link_404_immediately(manager, adult): ...   # Review Focus 5
def test_profile_header_for_stranger_is_404(...): ...
def test_cross_tenant_member_is_404(...): ...                # canary
def test_delete_me_and_export_refuse_profile_header(...): ...
def test_audit_records_manager_as_actor(...): ...
def test_child_cannot_be_given_a_phone_later(...): ...       # child rows stay phone-less: no login for them
```

- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement. `current_ctx` checks `X-Profile` against `family_links WHERE manager_id = session user AND member_id = header AND status = 'active'` on every request (no caching, so revoke is instant). Web: the switcher in `Band` lists "Me" plus active members; the choice lives in `sessionStorage` and every `api` call sends it.
- [ ] **Step 4:** Backend suite, web checks, `docker compose restart web`. Expected: green.
- [ ] **Step 5:** Commit `feat: family profiles with per-member consent`.

### Task 12: Share with a doctor

**Files:**
- Create: `backend/app/share.py`; `web/src/pages/Shared.tsx`
- Modify: `backend/app/main.py`, `web/src/routes.ts` (`/s/:slug/:token`), `web/src/pages/Report.tsx` (Share button), `web/src/api.ts`
- Test: `backend/tests/test_share.py`

**Interfaces:**
- Produces: `POST /api/share` `{report_ids: list[UUID] (1–20), hours: int (1–168, default 24)}` → `{url, expires_at}`; `GET /api/share` (own links); `DELETE /api/share/{id}`; public `GET /api/share/{slug}/{token}` → `{expires_at, reports: [report_detail minus chat and file]}`; an expired, revoked or unknown token returns 404 `not_found`.

- [ ] **Step 1: Failing tests**

```python
def test_share_roundtrip_without_session(...): ...
def test_token_stored_hashed(...): assert token not in str(_row("share_links"))
def test_expired_and_revoked_are_404(...): ...
def test_share_excludes_pending_red(...): ...        # Review Focus 1: creating with it is 409 under_review; if it turns held later, the view omits it
def test_someone_elses_report_cannot_be_shared(...): ...   # 404
def test_every_view_audited(...): ...                # action share_view, actor NULL
def test_wrong_slug_with_valid_token_is_404(...): ...
```

- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement. `secrets.token_urlsafe(32)`, store `sha256`. The public route resolves the tenant from the slug, then reads inside `tenant_tx`. Response headers `Cache-Control: no-store` and `Referrer-Policy: no-referrer`. The web page is read-only, shows "Shared by the patient, expires …", and has no nav.
- [ ] **Step 4:** Backend suite, web checks, `docker compose restart web`. Expected: green.
- [ ] **Step 5:** Commit `feat: time-limited read-only share links`.

### Task 13: Evals, security review, results

**Files:**
- Create: `evals/datasets/trend_cases.json`
- Modify: `evals/run.py` (suites `trends` and `held`), `.github/workflows/ci.yml` (run both offline), `evals/RESULTS.md`, `phases/phase-2-timeline-doctor.md` (tick Done when)

- [ ] **Step 1:** `trend_cases.json`: at least 20 series (the Task 3 table plus mixed units and one-sided ranges), each with the expected `(direction, toward)` or `null`. Suite `trends` runs `convert` + `detect_trends` on each. Suite `held` runs the 15 fixture specs through `template_result` and `visibility.patient_view(held=True)` for every red one, and asserts no `critical` flag, no red triage and no result value appears in the JSON.
- [ ] **Step 2:** `cd backend && uv run python ../evals/run.py trends; uv run python ../evals/run.py held`. Expected: `trends: N/N`, `held: 15/15` (non-red specs pass trivially).
- [ ] **Step 3:** Run `security-review` on the branch. Focus: share tokens, the `X-Profile` path, doctor routes, held reports. Fix findings test-first.
- [ ] **Step 4:** Full checks: backend suite + ruff, web vitest/tsc/lint/build, `docker compose up -d --build`, then walk through the Done when list by hand (three HbA1c reports, mixed glucose, a red report held then released by timeout with `review_timeout_minutes` set to 1).
- [ ] **Step 5:** Record numbers in `evals/RESULTS.md`, tick the spec's Done when boxes, commit `docs: phase 2 eval results`.
