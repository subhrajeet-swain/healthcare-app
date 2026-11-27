# Backlog

Deferred items, newest first. Each names where it came from.

## From the phase 2 and 3 final reviews (2026-11-27)
- **Webhook parse drops the rest of a batch.** `whatsapp.parse` has one try around the whole payload; a malformed message drops every later one (200 returned, Meta won't resend). Try per message. (phase 3 Low.)
- **Link-code brute force.** 6-digit codes, per-sender cap only; many numbers could guess a live code. Lab-wide failed-LINK cap or 8+ digits. (phase 3 Low.)
- **WhatsApp window over 1 h backlog.** 23 h margin added; a longer queue delay still loses free text. Fall back to a template on Meta error 131047. (phase 3 Medium, partly fixed.)
- **Family invite phone enumeration.** Staff numbers get `not_a_patient`; unknown numbers create user rows without a daily cap. Uniform response + cap. (phase 2 Low.)
- **`?profile=<uuid>` in logs and history.** Allow it only on SSE/file routes or use a short-lived signed token. (phase 2 Low.)
- **Doctor decision after the graph thread is gone.** Decision saved but no doctor note or `review_complete` notify. Store final status and queue the notify anyway. (phase 2 Low.)

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
