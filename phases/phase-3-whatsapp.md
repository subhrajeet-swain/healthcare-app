# Phase 3: WhatsApp channel

Status: not started. Depends on: phases 1 and 2. **Start Meta onboarding during phase 1**, because approval takes time. See [PLAN.md](../PLAN.md).

## 1. Plan

**Goal:** a patient can do on WhatsApp what they do on the web (send a report, get the explanation, chat about it, get alerts), with the same brain and the same data. Web chat and WhatsApp both stay, side by side.

**In scope**
- **WhatsApp Cloud API** directly from Meta (no reseller): a business account, a phone number, and a webhook.
- **Linking:** a WhatsApp number is matched to a patient by an OTP sent in the app, or by a link code. The tenant comes from **which business number the patient messaged** (one number per lab, or a shared number plus a lab choice at link time), never from message text.
- **Inbound:** text, PDF and image messages. Media is downloaded through the Graph API, stored, and run through the same pipeline as phase 1.
- **Outbound:** the reply from the same `brain.answer()` as web chat. Status updates ("your report is being read…", "ready").
- **Message templates** (pre-approved by Meta) for messages outside the 24-hour window: report ready, trend alert, review complete. Red results get a template that says to call or open the app; **the values themselves are never put in a template.**
- **One conversation history:** web and WhatsApp messages go into the same `chat_messages`, tagged with their channel.
- **Opt-in and opt-out** ("STOP"), stored as consent.
- **Webhook security:** check the signature on every request, ignore duplicates (WhatsApp retries), reply 200 fast and do the work in a background job.

**Out of scope:** WhatsApp voice notes as input (later, through phase 4's speech to text), WhatsApp calling, payments.

**Design notes**
- A channel adapter is a thin module: `whatsapp.parse(webhook) -> Inbound` and `whatsapp.send(Outbound)`. The brain does not know about channels.
- Identity on WhatsApp: owning the number is not enough for red results. Ask for the date of birth before showing them (R1, the same rule as voice).
- Message length and formatting: WhatsApp allows simple markdown. Explanations are split into short messages.

**Done when**
- [ ] The same PDF sent on WhatsApp and on the web gives the same explanation, colour and next step.
- [ ] A conversation started on WhatsApp can be continued in the web chat, and the other way round.
- [ ] A forged webhook (bad signature) is rejected, and a duplicate delivery is processed once.
- [ ] Red-result values never appear in a template message.
- [ ] Opt-out stops all outbound messages.
- [ ] `security-review` is clean: webhook, media download, number linking.

**Risks**
- **Meta business verification** needs a business identity. As an individual this may stall. Start in test mode: Meta allows a test number that messages a few verified recipients. *Unverified in detail; check Meta's docs at the start.*
- Template rejections: write them plain and factual, with no medical claims.
- Health-data rules on WhatsApp: Meta's policies on healthcare messaging need reading before go-live.

## 2. Stack and costs

| Need | Choice | Cost |
|---|---|---|
| WhatsApp API | Meta WhatsApp Cloud API | Meta moved to per-message pricing in 2025. Replies inside the customer's 24-hour window were free as of that change; utility templates are charged per message by country. **Check Meta's current India rate card before going live.** |
| Public webhook URL | A cloudflared tunnel in dev; the deployed VM later | free |
| Phone number | A new number not already on WhatsApp | the cost of a SIM |

## 3. Coding

1. Meta app, test number and webhook verification handshake.
2. Signature check and idempotency (the message id as the key). **TDD.**
3. Number linking with OTP.
4. Inbound adapter for text, PDF and image, feeding the existing pipeline.
5. Outbound adapter and splitting long messages.
6. Templates: write them, submit them, and send on events.
7. Merging channels in the chat history.
8. Evals: WhatsApp parity tests (the same cases as web chat).

## 4. Skills this phase
`superpowers:writing-plans`, `superpowers:test-driven-development` (webhook check, idempotency, linking), `ponytail`, `code-review`, `security-review`.
