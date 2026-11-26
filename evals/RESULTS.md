# Eval results

| Suite | Where | Result | Date |
|---|---|---|---|
| fixtures (explainer 811eb54: boundary 5, unit scale 2, grounding 2, safety 4, injection 2) | offline, CI | 15/15 | 2026-11-25 |
| chat (diagnosis, emergency, treatment in EN/HI; injected, unsourced, off-topic and garbage model output; red value) | offline, CI | 16/16 | 2026-11-25 |
| trends (30 series through `convert` + `detect_trends`: the Task 3 table, the rulings, one-sided ranges, mixed units, unconvertible units excluded) | offline, CI | 30/30 | 2026-11-26 |
| held (15 fixture specs through `template_result`; the 4 red ones through `visibility.patient_view(held=True)`: no critical flag, no red triage, no result value; the 11 others shown as they are) | offline, CI | 15/15 | 2026-11-26 |
| whatsapp (15 fixture specs as WhatsApp text: the 11 non-red ones carry the web explanation and closing line once, in chunks of at most 700, EN and HI; the 4 red ones send no text and their red copy and template hold no value; 17 COPY/TEMPLATES entries have no digit and no placeholder but `{lab}`) | offline, CI | 32/32 | 2026-11-27 |
| reports (15 synthetic PDFs, live Gemini gemini-3.5-flash-lite) | local, needs `GOOGLE_API_KEY_1` | 15/15; grounding EN 40/40, HI 40/40 (with fixtures 30/30) | 2026-11-26 |
| live check (5 sample PDFs, upload to explanation, `scripts/live_check.py`) | local, Docker stack | 5/5 under 30 s; slowest 29.6 s (CBC), others 6.7–13.3 s | 2026-11-26 |

Targets for `reports`, from the explainer: with fixtures 30/30; grounding 100% EN and HI
(model sentences only); 0 unsafe; 0 critical missed.

    cd backend && uv run python ../evals/run.py reports

Phase 2 checks, 2026-11-26: backend 547 passed (`-m "not live"`; run with the compose `worker` stopped, with it up the
job-driven tests fail), ruff clean; web vitest 69 passed, tsc, lint (warnings only) and build clean.

Phase 3 checks, 2026-11-27: backend 634 passed (`-m "not live"`; run with the compose `worker` stopped), ruff clean;
web vitest 70 passed, tsc, lint (warnings only) and build clean; offline evals fixtures 15/15, smoke 2/2, chat 16/16,
trends 30/30, held 15/15, whatsapp 32/32. The first `whatsapp` run found the closing line sent twice on every amber
report (the pipeline already stores it as the last statement); fixed in `whatsapp.report_paragraphs`, 25/32 to 32/32.
`scripts/wa_fake.py` checked against a local api: a good signature gets 200, a wrong one 401. Manual check of the
whole WhatsApp flow on the dev stack (LINK, REPORT, worker log): pending (needs `WA_APP_SECRET` in `.env`).
