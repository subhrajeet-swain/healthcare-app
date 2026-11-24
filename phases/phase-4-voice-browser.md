# Phase 4: Voice agent in the browser

Status: not started. Depends on: phases 1 and 2 (phase 3 is not required). See [PLAN.md](../PLAN.md) and `personal/HEYDOC-VOICE-ARCHITECTURE.md`, which this phase builds.

## 1. Plan

**Goal:** a real-time voice agent that talks about a patient's reports, built and **measured** on browser calls (WebRTC) before any phone line. This turns the "not tried yet" parts of the voice doc (latency, barge-in, the per-sentence gate) into numbers.

**In scope**
- **Text-simulated call first:** the full call state machine driven by typed turns, reusing the brain. All the logic is tested before any audio is involved.
- **Voice worker** (Pipecat): Silero VAD, smart-turn, speech to text, router, Tier 0/1 audio or Tier 2 model, the gate **per sentence**, then text to speech. One call per worker slot.
- **Browser call:** a "Call me" or "Talk to us" button in the web app, using the Pipecat client in React over a WebRTC transport.
- **Outbound flows** (the agent "calls" the browser): report ready, red result (R2: the patient acknowledges or is handed over), trend alert.
- **Inbound flow:** "what does my report say", "is it ready".
- **Identity check before any result** (R1): date of birth plus one more fact. Three failures lead to a hand-off and no data.
- **Barge-in:** the patient can interrupt; the state machine makes sure a critical message is still fully delivered (voice doc, section 3.8).
- **Hand-off to a human:** a queue in the staff console with a summary written by code. In this phase the "human" picks up in the browser.
- **Call log and replay:** transcript, audio, and per sentence the tier, the gate verdict and the latency of each step. It can be replayed in the staff console.
- **Symptom intake:** the patient describes symptoms; the doctor gets a **structured summary** (no diagnosis) in the review queue. Emergency words (chest pain, breathlessness and so on) trigger R3 at once: "call 112 / go to emergency now".
- **Call policy** (code), the result of the "calls cost ₹0" exercise:
  - Red: call within minutes, retry, then alert the doctor.
  - Amber trend: call once if the patient prefers voice or did not open the notification in 48 h.
  - Green: no call.
  - Quiet hours and a per-patient call cap, set per lab.
- **Latency measurement:** p50 and p95 per step and per tier, on every call.

**Out of scope:** phone lines (phase 5), Odia (phase 5), speech-to-speech models.

**Design notes**
- The state machine is a plain Python class with explicit states and the R1-R5 checks. **TDD.** Pipecat only carries audio frames to and from it.
- **No LangGraph in the live turn loop** (latency, and R1-R5 must be plain testable code). LangGraph runs **after** the call: summary, symptom summary for the doctor, follow-up and callback scheduling. LangSmith traces the Tier 2 model calls, sampled, with masking.
- The fact sheet is loaded once when the call starts: zero database reads per turn.
- Tier 0 audio is rendered once per lab and language, and cached.
- Recording and transcript are written at the end of the call; safety events (gate block, emergency, hand-off) are written immediately.
- **Decision to make at the start of this phase:** Pipecat on our own workers versus LiveKit Agents (LiveKit has a built-in dispatcher). Prototype both for a day; pick by latency and the amount of code.

**Done when**
- [ ] The text-simulated call passes scripted personas: calm, confused, wrong date of birth, interrupter, emergency, prompt injection.
- [ ] On a browser call, a red-result flow delivers the full critical message despite interruptions, and gets an acknowledgement or hands over.
- [ ] The gate blocks a deliberately unsafe Tier 2 sentence **before** it is spoken (shown in the replay).
- [ ] Measured latency is published in the repo for each tier; we say honestly whether 800 ms holds.
- [ ] No result is spoken before the identity check (eval).
- [ ] `security-review` is clean: call auth, recording access, transcript privacy.

**Risks**
- Latency on a laptop plus free tiers may be poor. Measure, then decide what to spend.
- Hindi speech to text and text to speech quality. Sarvam is a paid API; test with free credits.
- Echo and noise in the browser: use headphones in dev; echo cancellation is the browser's job.

## 2. Stack and costs

| Need | Choice | Cost (verify on vendor pages before spending) |
|---|---|---|
| Voice framework | Pipecat (open source), or LiveKit Agents | free |
| Transport | Pipecat's small WebRTC transport (peer to peer) | free |
| VAD / turn-taking | Silero VAD, smart-turn | free |
| Speech to text | Deepgram (signup credit); Sarvam for Hindi | per minute after the credit |
| Text to speech | Piper or Kokoro (local, English); Sarvam for Hindi | free locally / per character |
| Model (Tier 2) | Gemini Flash or Groq | free tier in dev |
| Recordings | Local disk, then object storage | small |

## 3. Coding

1. The call state machine plus the R1-R5 checks, with text simulation. **TDD.**
2. Persona eval runner, text only.
3. Pipecat worker with VAD, speech to text, the router and text to speech, on a browser test page.
4. Per-sentence gate in the stream.
5. Barge-in handling around critical messages. **TDD** at the state-machine level.
6. Outbound flows, and the call policy. **TDD.**
7. Hand-off queue and staff pickup.
8. Call log, recording and the replay UI (`impeccable`).
9. Symptom intake and the doctor summary.
10. Latency instrumentation and the published results.

## 4. Skills this phase
`superpowers:writing-plans`, `superpowers:test-driven-development` (state machine, R1-R5, call policy, barge-in), `ponytail`, `impeccable`, `archify` (call sequence diagram), `root-cause-debugging` (audio bugs), `code-review`, `security-review`.
