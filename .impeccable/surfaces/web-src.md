---
version: 1
slug: "web-src"
primary_target: "web/src"
related_targets: []
---

Scope: patient web app shell (login, consent, role dashboards), mode Operate, mobile-first 390px, desktop secondary.
Audience/job: Indian patients and family caregivers incl. older users; sign in with phone OTP, give consent, land on "Your reports"; later read reports and act on next steps.
Constraints: WCAG 2.2 AA, 16px+ body, 44px+ targets, state never by colour alone, Devanagari-ready.

## Direction contract
THESIS: A lab report reads like a medicine strip the patient already trusts: one perforated cell per result with a word state, and a batch panel for the facts. Refuses the rounded-card-with-status-chip health app.
OWN-WORLD: Foil grey ground #E7E9EC, ink #14181F, magenta product band #9C1458 for brand and active nav, green #0F6B5C (normal), burnt orange #C24A0E (attention), red reserved for critical. Barlow Condensed uppercase for headings and values, Noto Sans + Noto Sans Devanagari for text. Square corners, one hairline border system (#B9BEC5), dashed perforations between cells.
STORY: The patient sees who they are, what the lab found, and the one next step; nothing clinical is shown that code has not approved.
FIRST VIEWPORT: Magenta band at top with PRIME HEALTHCARE, the greeting and the English | हिंदी language switch (one language per screen); heading YOUR REPORTS; strip panels below; ink bottom nav (Reports, Chat, Family, Profile) with magenta top tick on the active item. Login: magenta band, phone field and one primary ink button.
FORM: assigned direction (Chemist Strip), position 6 of my resonance list; seed:eafa189f05f1363c. Raises: proportional timeline gaps; strict hairline system; hierarchy by scale contrast; fixed name-plate furniture per family member.
FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
