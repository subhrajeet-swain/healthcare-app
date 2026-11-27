# Backlog

Deferred items, newest first. Each names where it came from.

## From the phase 3.1 reviews (2026-11-27)
- **Per-chat media rate limit.** A linked chat can send unlimited files; each runs the pipeline and the paid model. Cap per chat per hour. (security-review Low 1; fits 3.2 metrics.)
- **Unlinked-spam limit before queueing.** The new-sender cap is checked in the worker after a row and a job exist for each message. Check it in `store_inbound`. (security-review Low 2.)
- **Per-channel new-sender cap.** The cap counts WhatsApp and Telegram together. (final-review Minor.)
- **Multi-chunk resend on retry.** A failed send mid-way re-sends earlier chunks (accepted by ruling T4; now on Telegram too).

## Carried from phase 3
- A doctor's edited chat line isn't pushed to WhatsApp/Telegram.
- Consent withdrawal doesn't revoke share links (phase 2).

## Chatbot (planned for 3.3)
- "What is my Hemoglobin?" answered with HbA1c; "Does it record CBC?" refused. Answer coverage questions in code, add one-line "what it measures" per test in `tests.json`, allow general education under the gate.
