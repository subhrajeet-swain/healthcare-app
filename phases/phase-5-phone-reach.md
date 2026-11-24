# Phase 5: Real phones and reach

Status: not started. Depends on: phase 4. See [PLAN.md](../PLAN.md).

## 1. Plan

**Goal:** take the voice agent off the browser and onto real phone calls, so elderly and rural patients can use it on any phone, in their language. The agent can also call the doctor.

**In scope**
- **Phone line through Plivo:** an Indian number, inbound and outbound calls, media streamed to the voice worker.
- **Tenant from the dialled number** (inbound) or the call job (outbound), never from caller ID (voice doc, section 6).
- **Voice-first for elderly and rural users:**
  - A "voice-first" flag on the patient: notifications become calls, not app or WhatsApp messages.
  - A caregiver can set this up for a parent (family profiles, phase 2).
  - Slower speech, shorter sentences, repeat on request, and a confirmation question after key facts.
  - DTMF fallback ("press 1 to repeat, 2 to speak to a person") for noisy lines.
- **Languages:** Hindi first, then **Odia**, then others by demand. Template audio is recorded or generated for each language. The fixed messages (urgent, closing) are checked by a native speaker.
- **Agent calls the doctor:** for a red result with no doctor action within the lab's timeout, the agent calls the doctor, reads the critical value (the doctor is verified by PIN), and records the acknowledgement. If there is no answer, the backup doctor is called, and then the lab admin.
- **Call outcomes:** answered, voicemail, busy, no answer, wrong person. Retry rules per outcome.
- **Calling rules:** quiet hours, a per-patient cap, and per-lab consent for automated calls. Check India's telemarketing and automated-call rules (TRAI) for transactional healthcare calls.

**Out of scope:** ABHA, multiple cells, autoscaling (phase 6).

**Design notes**
- Plivo is only a transport behind the same voice worker. The state machine does not change.
- Phone audio is 8 kHz: re-test speech-to-text accuracy and the VAD thresholds against browser audio. Keep the calibration settings per lab (lines differ).
- Wrong-person handling: if the person who answers fails the identity check, say only "a message from <lab>, please call back", with no data.

**Done when**
- [ ] A real call to a basic feature phone works end to end in Hindi: identity check, red result, acknowledgement.
- [ ] An Odia call passes a native-speaker review of the fixed messages.
- [ ] Doctor escalation: no action, then the doctor is called, then the backup, then the admin, all logged.
- [ ] Measured latency on phone calls is published next to the browser numbers.
- [ ] `security-review` is clean: phone-number handling, caller-ID spoofing, recording consent.

**Risks**
- Cost per minute adds up. Watch it daily, and put a hard cap in Plivo.
- The rules on automated calls, recording consent and number registration need checking before calling anyone other than yourself.
- Odia speech-to-text and text-to-speech quality may be weak. Test early with Sarvam; fall back to Hindi or English by the patient's choice.

## 2. Stack and costs

| Need | Choice | Cost (from the handoff; **verify on plivo.com before buying**) |
|---|---|---|
| Phone line | Plivo voice, India | about ₹0.40 a minute, plus about ₹200 a month for a number |
| Speech to text / text to speech (Hindi, Odia) | Sarvam | per-minute and per-character pricing; check sarvam.ai/api-pricing |
| Fallback | Deepgram / Piper | as in phase 4 |

## 3. Coding

1. Plivo number, inbound webhook and media stream to the voice worker.
2. Outbound dialler using the call policy and call jobs.
3. Call outcomes and retry rules. **TDD.**
4. Voice-first preference and caregiver setup.
5. Hindi tuning: 8 kHz speech-to-text tests, VAD calibration settings.
6. Odia template audio, plus the speech-to-text and text-to-speech integration.
7. Doctor escalation call flow with PIN verification. **TDD.**
8. Cost tracking per call and per lab.

## 4. Skills this phase
`superpowers:writing-plans`, `superpowers:test-driven-development` (retries, escalation), `ponytail`, `root-cause-debugging`, `code-review`, `security-review`.
