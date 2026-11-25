---
version: 1
slug: "web-src"
primary_target: "web/src"
related_targets: []
---

Scope: patient web app shell (login, consent, reports, report, chat, profile, lab console), mode Operate, mobile-first 390px, desktop secondary; the same system later ships as the native mobile app.
Audience/job: Indian patients and family caregivers incl. older users; sign in with phone OTP, give consent, see what the latest report says and the one next step, read results, ask about them.
Constraints: WCAG 2.2 AA, 17px reading floor, 48px targets, result state always a printed word, one language per screen (EN | हिंदी), Devanagari-ready, nothing clinical shown that code has not approved.

## Direction contract
THESIS: The report reads like a well-made fitness dashboard: one big number that says how the latest report went, word pills for its states, and one black pill to the next step. Refuses the blue-and-teal hospital portal with icon tiles and a stock-photo doctor.
OWN-WORLD: Mist ground #F2F2F3, white cards at 24px radius with a soft long shadow, ink #111111 for text and every action (black pills), grey #5E5E66 for meta. Colour only carries state: critical red #A3122E on #FBE7EA, attention #9A4A08, normal green #0F6B5C, each with its word. Magenta #9C1458 survives as the one brand mark (avatar ring). Inter at heavy weights for numbers and headings, Noto Sans Devanagari for Hindi. No borders: cards separate by shadow, rows by 1px #ECECEE dividers.
STORY: The patient sees how their latest report went in one glance, the word for each state, and the one thing to do next; opens a report to read each result as a number tile; asks a question in the sheet at the foot.
FIRST VIEWPORT: Header: avatar initial with a magenta ring, "Namaste" over the name, English · हिंदी pill at right. Summary card: LATEST REPORT · date label, test count at 44px, state pills (3 Normal, 1 Urgent), the next step line, full-width black "Open report" pill. A row of three stat tiles (reports, tests read, need a doctor). The report list card below. Floating white pill tab bar (Reports, Chat, Profile; icon + label; current tab filled black) 22px off the bottom. Signature move: the big-number summary card with word pills.
FORM: seed: none (pinned) — the user chose "A · Clean Monochrome" from three mocked looks ("Go with A"), after supplying @uix.vikram's fitness-app shots as the reference.
FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
