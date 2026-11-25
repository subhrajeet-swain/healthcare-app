# Phase 1: Report vault, web chat and the safety brain

Status: built on branch `phase-1` (2026-11-25); live checks wait for a rotated Gemini key. Depends on: phase 0. See [PLAN.md](../PLAN.md).

## 1. Plan

**Goal:** the first real product. A patient uploads a lab report, watches its status, gets a safe plain-language explanation with a triage colour, and can chat about it. Lab staff can upload reports for patients. The safety brain built here is the one every later channel reuses.

**In scope**
- **Upload** a PDF or a photo, from the patient or from lab staff for a patient. File limits, type checks, a virus-scan placeholder, and storage in a per-tenant folder.
- **Extract**, reusing `extract.py`: the text layer first; scanned pages and photos go to the model's vision. The output is schema-validated JSON, with units normalised into `results` rows.
- **Flag and next step**, reusing `flags.py` and `nextstep.py`, unchanged where possible.
- **Explain and verify**, reusing `explain.py` and `ground.py`. Every sentence is tagged with its source (R4).
- **Safety brain module** (`backend/app/brain/`): the fact-sheet builder, the router (Tier 0 script, Tier 1 template, Tier 2 model through the gate), and the gate. It is one function that every channel calls.
- **Triage colour** (red, amber, green) on each report and each result.
- **Status tracking**, a step list rather than a map: `received`, `extracting`, `explaining`, then `needs_review` or `ready`, then `notified`. For lab uploads, `sample collected` and `in lab` come first. The page updates live through SSE (LISTEN/NOTIFY), with polling as a fallback.
- **Web chat about a report**: questions are answered only from that report's fact sheet. Off-topic or diagnosis requests get a fixed safe reply.
- **Report view**: values, ranges, colours, the explanation, the next step, and the original PDF through a short-lived link.
- **Languages:** English and Hindi (the explainer already has Hindi messages in `nextstep.py`). The web app shows one language at a time, chosen in the band (decided 2026-11-25).
- **Evals:** port the explainer's 30 eval cases and 40 grounding cases; add chat cases (prompt injection inside the PDF, "what's my diagnosis", "is this cancer").

**Out of scope:** the timeline across reports, doctor review (red results show "your doctor will be told", and the alert path arrives in phase 2), WhatsApp, voice.

**Design notes**
- The pipeline runs in the **background worker**, never inside the upload request.
- **LangGraph:** the pipeline is a `StateGraph` (extract, then flag, then next step, then explain, then verify, then triage) with the Postgres checkpointer, so a crash resumes from the last finished step. The flag, next-step and triage nodes are plain functions; only extract and explain call a model.
- **LangChain:** the model calls move from Google ADK to `langchain-google-genai` with structured output. The chat uses `create_agent` with middleware in this order: `PIIMiddleware`, then model fallback (Gemini, then Groq), then a custom `SafetyGateMiddleware` that runs `ground.py` after the model and replaces a failing answer with a template.
- **LangSmith:** every pipeline run and chat turn is traced with masking; the ported evals run as LangSmith experiments.
- Copy the explainer modules into `backend/app/brain/`, with their provenance noted at the top of each file. Do not import the old repo.
- Explanations are stored; viewing a report never calls the model again.
- The chat fact sheet stays in memory per session (a small LRU, ponytail), so there are zero database reads per chat turn after the first.
- A red result is never explained by the model alone: a Tier 1 template with the urgent message (`nextstep.urgent_message`).

**Done when**
- [ ] The 3 sample Drlogy PDFs (CBC, lipid, thyroid) and `B080.pdf` / `Z005.pdf` go from upload to explanation in under 30 s, with live status.
- [ ] The ported evals pass at the same scores as the explainer (30/30 eval, 40/40 grounding). Offline half done: fixtures 15/15. Live `reports` suite pending the key.
- [x] The chat refuses diagnosis questions and survives the prompt-injection cases (offline evals: chat 16/16, injection fixtures 2/2; live model run pending).
- [x] Canary tests still pass with reports in the database.
- [ ] The UI passes an `impeccable` review.
- [ ] `security-review` is clean: file upload, signed links, injection.

**Risks**
- Photo OCR quality. Measure on real phone photos; if it's poor, mark photos as beta.
- Free-tier model data use. Sample PDFs only (PLAN section 9).

## 2. Stack and costs

| Need | Choice | Cost |
|---|---|---|
| PDF text | pypdf / pdfplumber | free |
| Extraction and explanation | Gemini through Google ADK (as in the explainer) | free tier in dev; check rate limits; a paid tier is needed for real data |
| Second model | Groq (OpenAI-compatible API) | free tier; check limits |
| Files | Local disk; S3-compatible storage when deployed | free / a few ₹ |
| Live status | SSE in FastAPI + Postgres LISTEN/NOTIFY | free |
| Charts (report view) | Decided at the start of the phase; something small (for example uPlot or Recharts) | free |

## 3. Coding

1. Copy the brain modules over and get their original tests passing in the new repo.
2. `reports` and `results` tables and the upload endpoint with storage.
3. Background worker: job claim (`SKIP LOCKED`), the pipeline steps and status updates.
4. SSE status stream and the status-tracker UI.
5. Fact-sheet builder, router and gate as one module. **TDD.**
6. Triage colour. **TDD.**
7. Report view UI (`impeccable`).
8. Chat endpoint and chat UI.
9. Lab-staff upload flow.
10. Port the evals and add the chat and injection cases.

## 4. Skills this phase
`superpowers:writing-plans`, `superpowers:test-driven-development` (brain, triage), `ponytail`, `impeccable`, `archify` (upload-to-explanation data flow), `root-cause-debugging`, `code-review`, `security-review`.
