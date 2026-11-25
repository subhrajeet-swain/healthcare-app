# Eval results

| Suite | Where | Result | Date |
|---|---|---|---|
| fixtures (explainer 811eb54: boundary 5, unit scale 2, grounding 2, safety 4, injection 2) | offline, CI | 15/15 | 2026-11-25 |
| chat (diagnosis, emergency, treatment in EN/HI; injected, unsourced, off-topic and garbage model output; red value) | offline, CI | 16/16 | 2026-11-25 |
| reports (15 synthetic PDFs, live Gemini) | local, needs `GOOGLE_API_KEY` | not run yet (key rotation pending) | — |

Targets for `reports`, from the explainer: with fixtures 30/30; grounding 100% EN and HI
(model sentences only); 0 unsafe; 0 critical missed.

    cd backend && uv run python ../evals/run.py reports
