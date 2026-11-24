# Phase 6: ABHA and scale-up

Status: not started. Depends on: phases 1-5. See [PLAN.md](../PLAN.md).

## 1. Plan

**Goal:** bring in reports from outside the app through ABHA, and prove the system holds the target scale (PLAN section 4), with real numbers instead of arithmetic.

**In scope: ABHA / ABDM**
- Link a patient's **ABHA number** (create one or link an existing one) through the ABDM sandbox.
- Act as an **HIU** (Health Information User): request consent and pull reports from other providers. FHIR bundles are converted into our `reports` and `results`.
- Possibly act as an **HIP** (Health Information Provider) so reports in our app can be shared out. Decide at the start of the phase.
- Consent artefacts stored and honoured: expiry, revoke, and the purpose limits.
- Pulled reports go through the same pipeline (flags, trends, colours) and are tagged by source.

**In scope: scale**
- Load tests at 5x the busiest hour, for chat, uploads and voice (simulated callers), **with the canary tests running at the same time**.
- Voice worker autoscaling on **open calls**, with a warm pool and a dispatcher that pulls by free slot; reserved inbound capacity with a "we'll call you back" overflow.
- Provider token buckets per client; a second provider for speech to text, text to speech and the model, with automatic failover.
- PgBouncer (transaction mode), read replicas for timeline reads, monthly partitions for `audit_log`, `call_events` and `chat_messages`.
- **Cells:** a written, tested setup that stands up a second cell and moves one test lab into it.
- Dashboards: open calls, p95 per tier, gate blocks, hand-off rate, cost per call, provider errors.
- **Decision:** self-hosted GPUs versus per-minute APIs, using phase 4 and 5 numbers (the break-even minutes per month).

**Out of scope:** new patient-facing features.

**Design notes**
- FHIR parsing is one adapter: `fhir_bundle -> ExtractedReport`. After that everything is the existing pipeline.
- Kubernetes only if running several cells by hand is clearly painful. Otherwise, Docker Compose per cell plus a load balancer.

**Done when**
- [ ] The sandbox flow works: link an ABHA, get consent, pull a report, and it shows on the timeline with the right colours.
- [ ] The load test passes at 5x peak with p95 targets met, and **zero canary leaks**.
- [ ] Killing one provider mid-test moves traffic to the second with no dropped red-result call.
- [ ] A second cell is stood up from the written runbook, and a lab is moved without data loss.
- [ ] The GPU-versus-API decision is written down with the numbers.
- [ ] `security-review` is clean: ABDM integration, consent artefacts.

**Risks**
- **ABDM sandbox access may need a registered organisation.** Unverified. Check eligibility before starting the phase. If it's blocked, ship the scale half and park ABHA.
- FHIR profiles from different providers vary. Start with the lab-report (DiagnosticReport) profile only.
- Load-testing voice needs synthetic audio callers. Reuse the phase 4 personas with text to speech as the caller.
- Cloud cost during load tests: run them in short, capped windows.

## 2. Stack and costs

| Need | Choice | Cost |
|---|---|---|
| ABHA | ABDM sandbox APIs (gateway, HIU, consent manager) | free sandbox; production terms unknown |
| FHIR | `fhir.resources` (Python) | free |
| Load testing | Locust (HTTP); synthetic Pipecat callers (voice) | free, plus cloud hours |
| Pooler / replicas | PgBouncer; a managed Postgres read replica | depends on the cloud; decide then |
| Monitoring | Prometheus + Grafana (self-hosted) or a free tier | free / small |

## 3. Coding

1. ABDM sandbox registration and the gateway auth handshake.
2. ABHA create or link flow.
3. HIU consent request, data pull, and FHIR to `ExtractedReport`. **TDD** on the mapping.
4. Consent-artefact storage, expiry and revoke.
5. Metrics and dashboards.
6. Provider token buckets and failover. **TDD.**
7. Voice dispatcher, warm pool and autoscale on open calls.
8. Load-test harness: HTTP plus voice personas, with canaries running alongside.
9. The cell runbook and moving a lab between cells.

## 4. Skills this phase
`superpowers:writing-plans`, `superpowers:test-driven-development` (FHIR mapping, failover), `ponytail`, `archify` (cells and scaling diagram), `root-cause-debugging`, `code-review`, `security-review`.
