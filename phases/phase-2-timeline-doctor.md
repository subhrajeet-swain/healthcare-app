# Phase 2: Timeline and doctor-in-the-loop

Status: not started. Depends on: phase 1. See [PLAN.md](../PLAN.md).

## 1. Plan

**Goal:** turn single reports into a health history, catch trends in code, and put a doctor between risky findings and the patient.

**In scope**
- **Longitudinal timeline:** every report for a patient merged per test (analyte) over time, with a chart per test showing its reference band.
- **Matching tests across reports:** map test names to a canonical code ("HbA1c", "Glycated Haemoglobin", and so on). Start with a hand-made synonym table for the ~50 most common tests; LOINC mapping comes later.
- **Unit normalisation** (mg/dL against mmol/L, and so on), with a table of conversion factors. If units cannot be converted, the point is excluded from the trend and the patient is told why.
- **Trend detection** (code, not model): for each test with at least 3 points, the direction, the size of the change, and whether it is moving out of range or toward a critical limit. Values are compared **relative to each lab's own range** where the labs differ.
- **Trend alerts** ("sugar rising over 3 reports") create a `trends` row, coloured amber, which feeds the review queue and later the call policy.
- **Doctor review queue:** anything red, every trend alert, and chat answers the gate flagged as uncertain. The doctor can approve, edit (from fixed options), or escalate. The patient sees "under review" until then.
- **Doctor alerts** for red results: in-app plus email in this phase. The call to the doctor comes in phase 5.
- **Family profiles:** one account manages linked members (parent, child), with consent recorded per member. Adults must accept the link.
- **Share with a doctor:** a time-limited, read-only link to selected reports, with every view audited.

**Out of scope:** WhatsApp, voice, ABHA, outside doctors with their own accounts (sharing is by link only).

**Design notes**
- The trend rules sit in one pure function `detect_trends(results) -> list[Trend]`, with table-driven tests.
- The review queue uses **LangGraph `interrupt()`**: the report graph pauses at a review node, a `review_items` row points at the paused thread, and the doctor's decision resumes it (`Command(resume=…)`). The timeout escalation is a scheduled job that resumes the thread with "escalate".
- Timeline reads are a single indexed query per patient (`results` by patient, test code and date). No new store.

**Done when**
- [ ] Three synthetic HbA1c reports (6.1, then 6.5, then 7.0) produce a "rising" trend, an amber colour, and a review item. (trend and review item proven by `test_three_hba1c_reports_make_one_amber_trend_and_review`; the amber pill in the browser: manual check pending)
- [ ] A mixed-unit series (glucose in mg/dL and mmol/L) trends correctly, and a series that cannot be converted is excluded with a reason shown. (trend and exclusion proven by `evals trends` 30/30 and `test_trends_store`/`test_timeline`, which return the reason; the reason line in the browser: manual check pending)
- [x] A red result is hidden from the patient until a doctor acts or a timeout escalates it (the timeout is set per lab). (`test_visibility`, `test_review_flow::test_timeout_escalates`, `test_review_timeout_comes_from_tenant_settings`, `evals held` 15/15)
- [x] A family member's data is visible only after consent; canary tests cover family links. (`test_family`: pending invite 404 until accepted, no upload without the member's consent, revoked link 404; `test_canary` covers `family_links`)
- [ ] `security-review` is clean: share links, family access. (deferred by the user; not run)

**Risks**
- Name and unit mapping is the real work. Keep the synonym table small and grow it from real reports.
- Doctor availability in a personal project: use test doctor accounts. A real deployment needs the lab's pathologist on board.
- Medical correctness of trend thresholds. Get them checked by a clinician before any real use.

## 2. Stack and costs

| Need | Choice | Cost |
|---|---|---|
| Charts | The library chosen in phase 1 | free |
| Doctor email | SMTP (for example Gmail in dev, a transactional provider later) | free |
| Everything else | Existing stack | ₹0 |

## 3. Coding

1. Canonical test codes, the synonym table and unit conversion. **TDD.**
2. `detect_trends`. **TDD**, table-driven.
3. The `trends` and `review_items` tables, and the hooks from the pipeline.
4. Doctor queue UI and actions (`impeccable`).
5. Timeline UI with a chart per test.
6. Family links with consent.
7. Share links.
8. Evals: trend cases, and "patient sees nothing red before review".

## 4. Skills this phase
`superpowers:writing-plans`, `superpowers:test-driven-development` (mapping, units, trends), `ponytail`, `impeccable`, `code-review`, `security-review`.
