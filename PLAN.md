# Healthcare app with a voice agent: overall plan

Status: planning. No code yet. Written 2026-11-24.

This is a personal project, built as if I were the engineer at HeyDoc responsible for it from scratch. It grows out of two things I already have:

- The **lab report explainer** (`personal/heydoc-lab-explainer/`), which is text only, has one client, and is measured: eval 30/30, grounding 40/40.
- The **voice architecture write-up** (`personal/HEYDOC-VOICE-ARCHITECTURE.md`), which is a design on paper and has never been built.

Each phase has its own file in `phases/`. This file holds what is shared: the product, the users, the scale, the system design, the stack overview and the rules every phase follows.

---

## 1. The product in one paragraph

A patient gets a lab report as a PDF from a lab or from their own files. They upload it on the web, or send it on WhatsApp. The app reads it, explains it in plain language (English, Hindi, and later Odia and others), colours it red, amber or green, and keeps every report on one timeline. Code watches that timeline for trends ("your sugar has risen over 3 reports"). When something matters, the agent **calls** the patient, which suits elderly and rural users who may never open an app. It checks the patient's identity, says only what code has approved, and hands over to a human or a doctor when needed. Doctors review anything risky before it reaches the patient. Later, ABHA links bring in reports from other hospitals.

## 2. Users

| Who | What they need | Main channel |
|---|---|---|
| Patient (smartphone) | Upload, understand, see trends, ask questions | Web app, WhatsApp |
| Elderly or rural patient | Be told what matters in their language, without an app | Phone call (voice-first) |
| Family caregiver | Manage parents' and children's reports from one account | Web app, WhatsApp |
| Lab staff | Upload results, see status, handle hand-offs | Staff web console |
| Doctor (lab pathologist or GP) | Sign off risky answers, get critical alerts | Review queue, phone call |
| Lab admin (the client) | Settings, scripts, critical limits, reports | Admin console |
| Platform admin (us) | Onboard labs, watch health, run evals | Ops console, logs |

## 3. Core rules (apply to every phase and channel)

These carry over from the explainer and the voice doc. They do not change.

1. **Code decides anything clinical.** Flags, severity, triage colour, trends, next step and who gets called are ordinary, tested code. The model only phrases facts that code has already approved.
2. **One safety brain, every channel.** The web chat, WhatsApp and voice all go through the same fact sheet, gate (`ground.py`) and rules R1-R5. A channel is only a transport.
3. **Fails closed.** If the gate is unsure, the sentence is not shown or spoken. It falls back to a template, then to a human.
4. **Clients are walled off.** The tenant comes from how the request arrives (login, number dialled, call job), never from what anyone types or says. Postgres row-level security, keys per client, canary tests.
5. **The model never sees identifiers.** No names, phones or ids reach the model. Claims use local names (`c1`, `report_1`).
6. **Calm, clear, never alarming.** Critical news leads with what to do next. Never "don't worry".
7. **No diagnosis, no prescription.** The app explains results and points to the next step. A doctor decides.

**R1-R5** (from the voice doc): R1, no results before the identity check. R2, critical results need acknowledgement or a hand-off. R3, an emergency can interrupt at any step. R4, every sentence is tagged with its source. R5, the client stays fixed for the whole call or session.

**Triage colours** (code, from `flags.py`):
- **Red:** a critical value. Doctor alert, call the patient, needs acknowledgement (R2).
- **Amber:** abnormal or a trend. Explanation plus "see your doctor". Call only if the call policy says so.
- **Green:** normal. Explanation and a notification only.

## 4. Scale targets

These are reused from the voice doc, section 7. **They are illustrations, not real HeyDoc numbers**, and we grow into them. The build starts as one cell on one machine. The design must not block the target.

| Measure | Target | Arithmetic |
|---|---|---|
| Lab clients | 20 | One cell at first, the client-to-cell table exists from day one |
| Interactions, all channels | 15M a month | about 5.8 a second on average, about 30 a second at peak (5x) |
| Voice calls | 1M a month | 0.4 calls a second; 3 minutes each, so about 70 open calls on average and a few hundred at the busiest hour |
| Reports uploaded | 2M a month (*assumption*) | about 0.8 a second on average; a PDF is about 300 KB, so about 600 GB a month |
| Call recordings | about 4 TB a month | from the voice doc's sizing |
| Patients | about 5M (*assumption*) | 250k per lab on average |

**Latency targets**
- Voice turn, from end of speech to first audio: **under 800 ms** is realistic for Tier 0, likely for Tier 1, and a stretch for Tier 2. These are estimates from vendor ranges and must be measured (phase 4).
- Web or WhatsApp chat: first token under 2 s.
- Report upload to explanation ready: under 30 s. It runs in the background and shows its status live.
- Status page update: under 3 s after the status changes.

**Where the bottleneck is:** media workers and provider concurrency limits (speech to text, text to speech, the model), **not the database**. See section 6.

## 5. System design

### 5.1 Shape: a modular monolith plus one separate worker type

```
                 ┌──────────── Web app (React) ────────────┐
 Patient/Staff ─►│ patient · staff console · doctor queue  │
                 └───────────────┬─────────────────────────┘
                                 │ HTTPS (REST + SSE)
 WhatsApp ─► Meta Cloud API ─► webhook ─┐
                                        ▼
                 ┌──────────── API (FastAPI monolith) ─────────────────┐
                 │ auth · tenants · reports · timeline · chat          │
                 │ safety brain (fact sheet, gate, rules R1-R5)        │
                 │ call policy · review queue · audit · consent        │
                 └──────┬───────────────────┬───────────────┬──────────┘
                        │ SQL (RLS)         │ jobs          │ files
                        ▼                   ▼               ▼
                   Postgres  ◄──── job queue (SKIP LOCKED)  object storage
                        ▲                   │
                        │                   ▼
                 ┌──────┴───── Workers ─────────────────────────────┐
                 │ background worker: extract, explain, trends,     │
                 │   notifications                                  │
                 │ voice worker (Pipecat): one call per slot,       │
                 │   STT → router → template / model → gate → TTS   │
                 └──────────────────────────────────────────────────┘
                        │                    │
           Browser WebRTC (phase 4)    Plivo phone line (phase 5)
```

**Why a monolith:** one developer, one deploy, and one database transaction for each piece of work. The only thing split out is the **voice worker**, because it scales on open calls rather than requests, holds a call open for minutes, and must not share a process with web requests. The background worker runs the same code as the API with a different entry point.

**What we do not add until a number says so:** Kubernetes, Kafka, Redis, microservices, a vector database. Postgres is the queue (`SELECT … FOR UPDATE SKIP LOCKED`), the cache is memory in each process, and live status uses Postgres `LISTEN/NOTIFY` pushed to the browser over Server-Sent Events (SSE).

### 5.2 Main flows

**Upload to explanation**
1. Web or WhatsApp upload. The file goes to object storage and a `report` row is created with status `received`.
2. A job is queued. The worker extracts (`extract.py`), flags (`flags.py`), picks the next step (`nextstep.py`), explains (`explain.py`) and verifies (`ground.py`).
3. The status moves through `extracting`, then `explaining`, then either `needs_review` or `ready`. Each change sends a NOTIFY, which updates the page over SSE.
4. Triage colour and trends are computed. The call policy decides: notify, call, or doctor alert.

**Chat turn** (web or WhatsApp): load the fact sheet for that report, which is built once and cached in memory, then router, then template or model, then the gate, then reply. The same function serves both channels.

**Voice call:** a call job (outbound) or the dialled number (inbound) fixes the tenant. Then the fact sheet is loaded, then the state machine runs (identity first, R1), then for each turn: router, tier, gate per sentence, TTS. Recording and transcript are written at the end; safety events are written immediately.

### 5.3 Data model (main tables)

`tenants`, `tenant_settings` (versioned), `users` (patients, staff, doctors, each with a role), `family_links`, `consents`, `reports`, `results` (one row per test value, normalised units), `trends`, `explanations` (sentences plus their source tag), `review_items`, `chat_sessions` and `chat_messages`, `calls` and `call_events`, `jobs`, `audit_log` (append-only, partitioned by month), `abha_links` (phase 6).

Every table has `tenant_id`, with row-level security forced on. Patient-identifying fields are encrypted with the client's key. Phone lookup uses a keyed fingerprint per client (voice doc, section 6).

### 5.4 Scaling path (the order to do things in, when a number demands it)

1. One machine with Docker Compose: API, worker, voice worker, Postgres. This lasts longer than expected.
2. Move Postgres to a managed service and add PgBouncer in transaction mode (`SET LOCAL` only).
3. Run several API and worker processes behind a load balancer; they keep no state, so this is easy.
4. Scale voice workers on **open calls**, with a warm pool and a dispatcher that pulls work by free slot. Inbound calls get reserved capacity; when full, the agent says "we'll call you back".
5. Provider token buckets per client, and two providers for each of speech to text, text to speech and the model.
6. Read replicas for timeline reads, monthly partitions for append-only tables.
7. **Cells:** a new copy of the whole stack for a group of clients. We grow by adding cells, not by sharding.
8. Kubernetes only when cells exist and managing many machines by hand hurts.

### 5.5 Efficiency rules
- Zero database reads per voice turn: the fact sheet is held in memory for the whole call.
- Template audio for Tier 0 is rendered once and cached.
- Model calls are cached by input hash (the explainer already does this in `cache.py`).
- Writes are batched, except safety events, which are written synchronously.
- Same report, same answer: explanations are stored, not regenerated on every view.

### 5.6 Where LangChain, LangGraph and LangSmith fit

Decided 2026-11-25: the project uses the LangChain ecosystem, partly for practice. The rule is that **the framework carries the plumbing and our code keeps the decisions**.

| Product | Used for | Not used for |
|---|---|---|
| **LangChain** (v1) | Model wrappers (`langchain-google-genai`, `langchain-groq`); structured output for extraction; `create_agent` for the web and WhatsApp chat agent; **middleware**: a custom `SafetyGateMiddleware` (after-model hook that runs `ground.py`, fails closed), `PIIMiddleware` (identifiers redacted before the model, rule 5), model fallback (Gemini, then Groq), and model-call limits | Deciding flags, severity, triage, trends or the call policy. These stay plain tested Python |
| **LangGraph** | The report pipeline as a graph with a Postgres checkpointer (durable, resumable steps); **doctor review through `interrupt()`** (phase 2); human-in-the-loop for hand-offs; post-call work such as summaries, symptom summaries and follow-up scheduling (phase 4) | The live voice turn loop. It stays Pipecat plus our own state machine, because of latency and because R1-R5 must be fully testable (the voice doc's decision stands) |
| **LangSmith** | Tracing of every model call outside the voice hot path; eval datasets and experiments (the ported 30 + 40 cases, chat and injection cases, personas); comparing prompt and model versions | Storing real patient data. Inputs are masked or hidden, and only synthetic data is used until a data agreement exists |

**Guardrails are layered, not replaced:** LangChain's guardrail middleware adds checks (PII, call limits, human approval), but the gate (`ground.py`) stays the final deterministic check and is wrapped as middleware, not swapped for a model-based guardrail.

**Tenant isolation with LangGraph:** checkpoint tables do not have row-level security. Thread ids are built as `tenant:{id}:…`, the checkpointer runs as a separate database role, and no patient identifiers are stored in graph state, only local names and ids. A canary test checks the checkpoint tables too.

### 5.7 Failure handling
- A provider is down: switch to the second provider. If both are down, chat uses templates only, and voice says "we'll call you back" and queues a callback.
- The gate blocks a sentence: fall back to a template, then hand over to a human. It never goes silent on a red result.
- A worker crashes mid-call: the call job is retried from its last state, and the patient gets a callback. A red result is never left unsent.
- The model returns garbage or invalid JSON: Pydantic validation fails and the template path is used.

## 6. Stack overview (detail and costs live in each phase file)

| Layer | Choice | Why |
|---|---|---|
| Backend | Python 3.12, FastAPI, Pydantic | Reuses the explainer as-is; Pipecat is Python |
| Packages | `uv` | Fast, one lock file |
| Frontend | React + TypeScript + Vite | Chat UI, charts, and the Pipecat React client; no server-side rendering needed |
| UI quality | `impeccable` skill | Avoid the generic AI-generated look |
| Database | Postgres 16 (Docker for dev) | Row-level security, queue, LISTEN/NOTIFY, partitions |
| Queue | Postgres `SKIP LOCKED` | No Redis or Kafka until needed |
| Live status | SSE + LISTEN/NOTIFY, polling fallback | No WebSocket server needed |
| Files | Local disk for dev; S3-compatible object storage when deployed | Short-lived signed links, a folder per tenant |
| Model | Gemini through LangChain (`langchain-google-genai`), Groq as the fallback | The explainer used Google ADK; its model calls are moved to LangChain. **Free-tier data may be used by the provider. Synthetic or sample reports only, until we're on a paid tier.** |
| Agents and middleware | LangChain v1 `create_agent` plus middleware | Chat agent, PII redaction, gate, fallback (section 5.6) |
| Workflows | LangGraph with the Postgres checkpointer | Report pipeline, doctor review via `interrupt()`, post-call work |
| Tracing and evals | LangSmith (free Developer plan to start; check current limits) | Traces, datasets, experiments. Inputs masked |
| Voice | Pipecat, Silero VAD, smart-turn | From the voice doc |
| Speech to text / text to speech | Deepgram (free credit) and Sarvam (Hindi, Odia) / Piper or Kokoro (free) and Sarvam | Hindi is weak in the free local models |
| WhatsApp | Meta WhatsApp Cloud API, direct (no reseller) | Phase 3 |
| Phone | Plivo, Indian number | Phase 5 |
| ABHA | ABDM sandbox | Phase 6, access unverified |
| Dev and run | Docker Compose; one VM in an Indian region when deployed | Data stays in India |

All prices are checked against vendor pages in each phase before spending. The handoff warned that third-party price figures conflict.

## 7. Phases

| # | Phase | One line | File |
|---|---|---|---|
| 0 | Foundation | Repo, login, tenants, row-level security, audit, consent, CI, eval skeleton | [phase-0-foundation.md](phases/phase-0-foundation.md) |
| 1 | Report vault + web chat + safety brain | Upload, extract, explain, triage colour, chat, lab upload, status tracking | [phase-1-report-vault.md](phases/phase-1-report-vault.md) |
| 2 | Timeline + doctor-in-the-loop | Trends, trend alerts, review queue, family profiles | [phase-2-timeline-doctor.md](phases/phase-2-timeline-doctor.md) |
| 3 | WhatsApp channel | Same brain on WhatsApp, PDF upload there, templates | [phase-3-whatsapp.md](phases/phase-3-whatsapp.md) |
| 4 | Voice agent (browser) | Pipecat calls in the browser, identity check, hand-off, replay, symptom intake, call policy | [phase-4-voice-browser.md](phases/phase-4-voice-browser.md) |
| 5 | Real phones + reach | Plivo, Hindi and Odia voice-first, agent calls the doctor | [phase-5-phone-reach.md](phases/phase-5-phone-reach.md) |
| 6 | ABHA + scale-up | ABDM link, cells, autoscale, failover, load tests | [phase-6-abha-scale.md](phases/phase-6-abha-scale.md) |

A phase is finished only when its "done when" checks pass, its security review is clean, and its evals are green. The next phase does not start before that.

## 8. How each phase is run (skills)

Every phase file follows the same three steps: **1. Plan, 2. Stack and costs, 3. Coding**.

| When | Skill | What for |
|---|---|---|
| Ideas for a new feature | `diverge` | Go wide before deciding |
| Start of a phase | `superpowers:writing-plans` | Turn the phase's coding section into step-by-step tasks |
| Diagrams | `archify` | Architecture and data-flow diagrams |
| Safety gate, rules R1-R5, flags, trends, call policy | `superpowers:test-driven-development` | Test first; a bug here is a wrong medical sentence |
| All code | `ponytail` | Least code that works |
| All UI | `impeccable` | Not the generic AI look |
| Bugs | `root-cause-debugging` | Root cause, not symptom |
| Before merging a phase | `code-review` | Correctness |
| End of each phase | `security-review` | Health data: tenant leaks, auth, injection, secrets |

## 9. Risks across the whole project

| Risk | Why it matters | What we do |
|---|---|---|
| Real patient data on free model tiers | Free tiers may let the provider use the data | Synthetic and sample PDFs only until on a paid tier with no-training terms |
| DPDP Act 2023 and its Rules | Consent, purpose, erasure and breach duties for health data | Consent and erasure built in phase 0; legal review before any real user |
| Software-as-medical-device rules (CDSCO) | Interpreting results could be regulated | No diagnosis or prescription, doctor sign-off on red results; check before launch |
| Lab ranges and units differ | Trends across labs could be wrong | Normalise units; compare values relative to each lab's range; flag mismatches (`flags.py` already detects unit mismatch) |
| Meta and ABDM onboarding need a business identity | Phases 3 and 6 could stall | Apply early; test mode and sandbox first; mark as a blocker if refused |
| LangSmith is a hosted service outside India | Traces could carry health data abroad | Mask or hide inputs and outputs; synthetic data only; decide on self-hosting or turning tracing off before real users |
| Framework weight and churn (LangChain) | More code paths, version changes | Use it at the edges listed in 5.6, pin versions, keep clinical logic framework-free |
| Voice latency is unmeasured | The 800 ms claim might not hold | Measure in phase 4 before promising anything |
| Scope is huge for one person | It may never finish | Each phase ships something usable; phases 0-2 alone are already a product |

## 10. Open decisions (decide at the start of the phase that needs them)

- A private GitHub repo now, or local only? (Recommended: private repo under `subhrajeet-swain`, pushed through the `github-personal` alias.)
- Where it is hosted when deployed: DigitalOcean Bangalore, AWS Mumbai or GCP Mumbai. Decide in phase 1 or 3, when a public webhook URL is first needed.
- Self-hosted GPUs versus per-minute APIs: decide in phase 6 using real numbers from phase 4.
- Pipecat on our own workers versus LiveKit: decide in phase 4.
