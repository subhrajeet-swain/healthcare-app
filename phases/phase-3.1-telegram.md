# Phase 3.1: Red results shown at once, fixes, Telegram channel

Status: not started. Depends on: phase 3 (branch `phase-3` @ c6c3bbe). Branch: `phase-3.1`.

## 1. Plan

**Goal:** a patient reads every report's explanation as soon as it is ready, including red ones, and can use the app through a Telegram bot with no business verification, payment or tunnel. WhatsApp code stays as it is, for a future partner lab that verifies its own number.

### A. Red reports are shown at once (user ruling, 2026-11-27)
- A red report is no longer held. Its results, explanation, triage and next step show to the patient as soon as the pipeline finishes, in every patient-facing place: detail, list, live status, chat, timeline, export, share links, family view and messaging channels.
- A red report always shows a fixed urgent banner first: "One or more results need attention today. Please call your lab or a doctor." It has a call button (`tel:` link to the lab's phone if one is set, else the banner text alone).
- The doctor review still happens: red and warnings reports still open a review item, still email the lab and still time out to escalate. The decision only adds the doctor's note line, as now. Nothing waits on it.
- The "Under review" screen goes away for red. A report under doctor review shows its values with a small "A doctor is also reviewing this report" note (the existing warnings-only behaviour).
- Messaging (WhatsApp and Telegram): a red report's explanation is sent too, always starting with the urgent line (`nextstep.urgent_message`). This replaces phase 3 ruling W1. WhatsApp templates still never carry values (Meta rule, unchanged).
- Phase 2 ruling Q6 and phase 3 ruling W1 are superseded; the held evals change to assert the urgent line instead of hiding.

### B. Fixes found in the phase 3 live run
- **Lost replies:** a WhatsApp message is marked handled before its replies are sent, so a failed send (network drop) loses the reply and the retry does nothing. Mark it handled only after the sends succeed. Linking and media must be safe to repeat (no second link, no second report on a retry). A duplicate reply on retry is acceptable; a lost one is not.
- **Latest report tie:** "latest report" (REPORT, questions) must use the same order as the report list: `coalesce(collected_on, created_at::date) DESC, created_at DESC`, then `id` for a stable tie-break.

### C. Telegram channel
- **Bot:** one bot from @BotFather. Settings: `telegram_bot_token`, `telegram_bot_username`, `telegram_lab` (the tenant slug the bot serves; one lab per bot, like one number per lab for WhatsApp). No token: the channel is off and sends only log, as WhatsApp.
- **Receiving:** long polling (`getUpdates`, timeout 30 s) in its own compose service, so there is no webhook and no tunnel. The poller only stores each update encrypted and queues a job (same rule as the WhatsApp webhook: no PHI in `jobs`, dedupe on the update id, the worker does the work).
- **Linking:** in the app, Profile → Telegram → "Connect Telegram" opens `https://t.me/<bot>?start=<code>`. Telegram sends `/start <code>`. The code is a long random token (Telegram allows 64 characters of `A-Za-z0-9_-`), stored hashed, 10 minutes, single use. Linking counts as opt-in (consent purpose `telegram`).
- **Commands:** `/start <code>` links; `/stop` withdraws consent; `/start` with no code re-grants it; `/report` sends the latest report. Any other text is a question (shared chat core, one history, channel `telegram`). A PDF or photo (the largest size) is downloaded with `getFile` and runs through the same checks and pipeline as an app upload (source `telegram`).
- **Alerts:** report ready, review complete and trend alert. Telegram has no 24-hour window and no templates, so it always sends free text (the explanation for report ready, red with the urgent line first).
- **Shared code:** linking, STOP/START, REPORT, questions, media and alerts are one implementation for both channels; each channel only has its adapter (parse, send, fetch media) and its own rules (WhatsApp: window and templates).
- **Web:** a Telegram strip on Profile (connect, status, unlink) and a "via Telegram" tag in chat.
- **Limits:** messages split at 4096 characters for Telegram (700 stays for WhatsApp); downloads capped at `files.MAX_BYTES`; only `api.telegram.org` is ever fetched.

**Out of scope:** Telegram inline keyboards and payments, group chats (a message from a group is ignored), several bots per lab, the app-wide chatbot (phase 3.3), logging and monitoring (phase 3.2).

**Done when**
- [ ] A new red report shows its explanation and the urgent banner at once in the app, with no "Under review" screen.
- [ ] The doctor queue still gets red reports, and a doctor's note appears on the released report.
- [ ] A failed WhatsApp or Telegram send is retried and the reply arrives; a retried LINK or media message does not link twice or create two reports.
- [ ] "Connect Telegram" in the app links the chat in one tap; `/report`, a question and a PDF work from Telegram.
- [ ] A conversation continues across web, WhatsApp and Telegram in one history.
- [ ] `/stop` stops all Telegram messages; red explanations on Telegram start with the urgent line.
- [ ] Live check with a real bot: link, `/report`, a question and a PDF upload from a phone.

## 2. Stack and costs

| Need | Choice | Cost |
|---|---|---|
| Messaging | Telegram Bot API (long polling) | free |
| Bot | @BotFather | free |

## 3. Skills this phase
`superpowers:writing-plans`, `superpowers:test-driven-development`, `ponytail`.
