# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users
Primary: patients and their family caregivers in India, on phones, including older users who are not confident with apps. They want to understand a lab report, see whether anything needs action, and know what to do next. Secondary (later phases): lab staff uploading results, doctors signing off risky findings, and lab admins. Elderly and rural patients without smartphones are served by voice calls, not this web app.

## Product Purpose
Prime Healthcare turns lab reports into plain-language explanations with a clear next step, keeps every report on one timeline, and calls the patient when something matters. Success: a patient understands their report and acts on red results; nothing unsafe is ever shown or spoken.

## Positioning
Code decides anything clinical (flags, severity, triage, trends, next step); the model only phrases facts code has approved, and every sentence passes a fail-closed safety gate. One safety brain serves web chat, WhatsApp and voice.

## Operating Context
Patients log in with a phone OTP, upload PDFs or photos of reports, chat about them on the web or on WhatsApp, and may receive voice calls. Each lab (client) is fully isolated. Doctors review red results and trend alerts before patients see them.

## Capabilities and Constraints
- Phase 0 (current): OTP login, consent, data export and delete, empty role dashboards. No report features yet.
- No diagnosis or prescription; the product explains and points to the next step.
- Languages: English and Hindi first, Odia later.
- Health data: DPDP Act consent and erasure; data stays in India; no real patient data on free model tiers.

## Brand Commitments
Name: Prime Healthcare. Voice: calm, clear, never alarming; critical news leads with what to do next; never "don't worry".

## Evidence on Hand
Sample lab report PDFs in `personal/` (Drlogy CBC, lipid, thyroid templates; B080.pdf; Z005.pdf). No users, testimonials, partners or certifications exist; do not invent any.

## Product Principles
1. Safety over fluency: when unsure, say less and hand over to a human.
2. The next step is always obvious.
3. Severity is never conveyed by colour alone.
4. Works for a first-time, older phone user.

## Accessibility & Inclusion
WCAG 2.2 AA plus older-user needs: 16px+ body text, large tap targets (min 44px), high contrast, no meaning by colour alone, Devanagari (Hindi) ready typography.
