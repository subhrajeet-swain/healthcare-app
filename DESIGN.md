---
name: Prime Healthcare
description: Patient lab-report app that reads like a well-made fitness dashboard, one big number, word pills, one black pill to the next step.
colors:
  mist-ground: "#f2f2f3"
  card-white: "#ffffff"
  sunk-well: "#f2f2f3"
  ink: "#111111"
  ink-hover: "#2a2a2e"
  ink-soft: "#5e5e66"
  divider: "#ececee"
  line: "#dcdce0"
  brand-magenta: "#9c1458"
  state-normal: "#0f6b5c"
  state-normal-tint: "#e3f1ed"
  state-attention: "#9a4a08"
  state-attention-tint: "#fcecdf"
  state-critical: "#a3122e"
  state-critical-tint: "#fbe7ea"
typography:
  display:
    fontFamily: "Inter, Noto Sans Devanagari, system-ui, sans-serif"
    fontSize: "2.75rem"
    fontWeight: 700
    lineHeight: 1
    letterSpacing: "-0.03em"
  headline:
    fontFamily: "Inter, Noto Sans Devanagari, system-ui, sans-serif"
    fontSize: "1.875rem"
    fontWeight: 700
    lineHeight: 1.1
    letterSpacing: "-0.02em"
  title:
    fontFamily: "Inter, Noto Sans Devanagari, system-ui, sans-serif"
    fontSize: "1.25rem"
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "-0.01em"
  body:
    fontFamily: "Inter, Noto Sans Devanagari, system-ui, sans-serif"
    fontSize: "1.0625rem"
    fontWeight: 400
    lineHeight: 1.5
    fontFeature: "tnum"
  label:
    fontFamily: "Inter, Noto Sans Devanagari, system-ui, sans-serif"
    fontSize: "0.9375rem"
    fontWeight: 600
    lineHeight: 1.3
  meta:
    fontFamily: "Inter, Noto Sans Devanagari, system-ui, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: 1.3
rounded:
  well: "16px"
  tile: "20px"
  card: "24px"
  pill: "999px"
spacing:
  "1": "4px"
  "2": "8px"
  "3": "12px"
  "4": "16px"
  "5": "20px"
  "6": "32px"
  "7": "48px"
  tap: "48px"
components:
  button-primary:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.card-white}"
    typography: "{typography.body}"
    rounded: "{rounded.pill}"
    padding: "0 20px"
    height: "52px"
  button-primary-hover:
    backgroundColor: "{colors.ink-hover}"
  button-quiet:
    backgroundColor: "{colors.sunk-well}"
    textColor: "{colors.ink}"
    rounded: "{rounded.pill}"
    padding: "0 20px"
    height: "52px"
  button-danger:
    backgroundColor: "{colors.state-critical}"
    textColor: "{colors.card-white}"
    rounded: "{rounded.pill}"
    padding: "0 20px"
    height: "52px"
  card:
    backgroundColor: "{colors.card-white}"
    rounded: "{rounded.card}"
    padding: "20px"
  stat-tile:
    backgroundColor: "{colors.card-white}"
    rounded: "{rounded.tile}"
    padding: "12px 16px"
  result-tile:
    backgroundColor: "{colors.card-white}"
    rounded: "{rounded.tile}"
    padding: "16px"
  result-tile-critical:
    backgroundColor: "{colors.state-critical-tint}"
  pill-normal:
    backgroundColor: "{colors.state-normal-tint}"
    textColor: "{colors.state-normal}"
    typography: "{typography.label}"
    rounded: "{rounded.pill}"
    padding: "0 16px"
    height: "36px"
  pill-attention:
    backgroundColor: "{colors.state-attention-tint}"
    textColor: "{colors.state-attention}"
    typography: "{typography.label}"
    rounded: "{rounded.pill}"
    padding: "0 16px"
    height: "36px"
  pill-critical:
    backgroundColor: "{colors.state-critical-tint}"
    textColor: "{colors.state-critical}"
    typography: "{typography.label}"
    rounded: "{rounded.pill}"
    padding: "0 16px"
    height: "36px"
  nav-item:
    textColor: "{colors.ink-soft}"
    typography: "{typography.label}"
    rounded: "{rounded.pill}"
    padding: "0 16px"
    height: "52px"
  nav-item-current:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.card-white}"
  input-pill:
    backgroundColor: "{colors.card-white}"
    rounded: "{rounded.pill}"
    padding: "0 16px"
    height: "52px"
  chat-user:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.card-white}"
    rounded: "{rounded.tile}"
    padding: "12px 16px"
  chat-assistant:
    backgroundColor: "{colors.sunk-well}"
    textColor: "{colors.ink}"
    rounded: "{rounded.tile}"
    padding: "12px 16px"
  brand-mark:
    backgroundColor: "{colors.card-white}"
    textColor: "{colors.brand-magenta}"
    rounded: "{rounded.pill}"
    size: "40px"
---

# Design System: Prime Healthcare

## Overview

**Creative North Star: "The Clean Monochrome Dashboard"**

A lab report read the way a good fitness app reads a run: one big number for how the latest report went, a word pill for each state, and one black pill to the next step. The ground is a quiet mist grey; everything the patient reads sits on white cards that lift off it with a soft, long shadow. Ink is near-black and carries every action. Colour is not decoration here; it appears only to carry a result state, and always next to the word that names it.

Density is low and the type is large, because many readers are older and read on a phone, in English or Hindi. One column, one container shape, one action colour. The same token values are meant to carry unchanged into the later native app, so every value is a plain hex, px or rem.

The system refuses the blue-and-teal hospital portal: no icon-tile grids, no stock-photo doctor, no tinted header band.

**Key Characteristics:**
- Mist ground, white cards at a generous radius, separated by shadow and never by a border.
- Ink black for text and every action; grey only for meta.
- Colour only for state, always paired with its word.
- Magenta appears once: the ring around the patient's initial.
- Big, heavy Inter numbers; Noto Sans Devanagari for Hindi.
- Pills for everything you press or read as a state.

## Colors

A monochrome system with one brand mark and three state colours that only speak with words.

### Primary
- **Ink Black** (ink): text, headings, and the fill of every action: primary buttons, the current tab, the selected language half, the user's chat bubble, the current progress step. Hover deepens to **Ink Hover** (ink-hover).

### Secondary
- **Prime Magenta** (brand-magenta): the brand mark only. A 2px ring and the initial letter inside the round mark at the start of the header. Never a fill, never a button, never text elsewhere.

### Tertiary (state)
- **Normal Green** (state-normal) on **Normal Tint** (state-normal-tint): results within range.
- **Attention Amber** (state-attention) on **Attention Tint** (state-attention-tint): results outside range that are not urgent.
- **Critical Red** (state-critical) on **Critical Tint** (state-critical-tint): urgent results, the danger button, error messages. A critical result tile takes the tint as its whole background.

### Neutral
- **Mist Ground** (mist-ground): the page itself, running to the top edge with no header band.
- **Card White** (card-white): every card, tile, the floating tab bar, the language pill, input pills.
- **Sunk Well** (sunk-well): quiet fills inside a card: fact wells, the quiet button, the assistant's chat bubble, boxed inputs at rest. Same value as the ground, used inside white.
- **Ink Soft** (ink-soft): dates, labels, hints, units, inactive tabs (5.9:1 on white, 5.3:1 on ground).
- **Divider** (divider): 1px hairlines between rows inside a card.
- **Line** (line): input outlines and the dashed file-picker well.

### Named Rules
**The Word First Rule.** Every state colour sits beside the word for that state ("2 normal", "Urgent", "outside range"). Colour reinforces; the word carries. A coloured dot or bar with no word is not allowed.

**The One Mark Rule.** Magenta appears once per screen, as the ring around the initial. Anything else that wants to be "brand" is ink.

**The Monochrome Action Rule.** Every action is ink black (or quiet grey, or critical red when it destroys). No coloured primary buttons.

## Typography

**Display Font:** Inter (variable, self-hosted), with Noto Sans Devanagari, then system-ui
**Body Font:** Inter, same stack
**Hindi:** Noto Sans Devanagari (self-hosted, 400 to 600), reached through the stack because Inter has no Devanagari

**Character:** One sans at heavy weights for numbers and headings and a regular weight for reading; numbers are tabular throughout so values line up.

### Hierarchy
- **Display** (700, 44px, 1): the summary number on the home card ("4 tests"). One per screen.
- **Headline** (700, 30px, 1.1): page titles, result values on number tiles, the triage next-step line.
- **Title** (700, 20px, 1.2): card titles.
- **Body** (400, 17px, 1.5): all reading text, capped at 34rem measure. 17px is the floor for anything a patient reads.
- **Label** (600, 15px): pills, tab labels, result names, row state words, small buttons.
- **Meta** (400, 14px): dates, units, ranges, stat labels, fact labels. Never for sentences the patient must act on.
- Stat numbers sit between title and headline (700, 28px, 1, -0.02em).

### Named Rules
**The Reading Floor Rule.** Body text is 17px. 14px is for meta only: a date, a unit, a label over a value.

**The One Language Rule.** A screen is in English or in Hindi, never both side by side. In Hindi, headings and big numbers drop negative tracking and open to 1.35 line height so matras have room, and uppercase is switched off.

## Layout

One centred column, max 40rem, 16px side gutters, on every width; desktop is the same column with more ground around it. Spacing runs on a 4px base (4, 8, 12, 16, 20, 32, 48). Cards stack with 16px between them; card content is inset 20px. Tiles sit in grids with 8px gaps: three stat tiles in a fixed row; result tiles auto-fill at a 9rem minimum. The header is one row: ringed mark, greeting over the patient's name (which wraps, never truncates), the language pill at the right. The patient tab bar floats at the foot, centred, 20px above the safe area; the page reserves scroll padding so content never hides beneath it. Below 30rem, buttons in an action row go full width.

Every tap target is at least 48px.

## Elevation & Depth

Depth is shadow-only and soft: two ambient shadows, both a low-alpha ink tint with a long blur. Surfaces never carry a border to separate them from the ground.

### Shadow Vocabulary
- **Card** (`box-shadow: 0 8px 24px rgba(17, 17, 17, 0.06)`): every resting card, stat tile, result tile, the language pill, the back circle, the brand mark.
- **Float** (`box-shadow: 0 10px 30px rgba(17, 17, 17, 0.12)`): things that hover above the page: the floating tab bar and the chat sheet.

### Named Rules
**The Shadow Not Border Rule.** Cards separate from the ground by shadow alone. Inside a card, rows separate by 1px divider hairlines. Outlines exist only on inputs.

## Shapes

Everything is rounded, and the radius tells you the size of the thing: cards 24px, tiles and chat bubbles 20px, inner wells and messages 16px, and every pressable thing a full pill. Round marks (the brand initial, the back button) are full circles. The chat card is the one sheet: a larger 28px top radius with a small grey grab handle, so it reads as a bottom sheet resting at the foot of the report.

## Components

### Buttons
Black, round, confident.
- **Shape:** full pill (999px), 52px tall; small buttons 48px.
- **Primary:** ink fill, white 17px/600 label, 20px side padding; often full width with a trailing arrow.
- **Hover / Active / Focus:** hover lightens to ink hover; press scales to 0.98; focus is a 3px ink outline, 3px offset. Transitions 160ms on an ease-out curve; none under reduced motion.
- **Quiet:** sunk-grey fill, ink text.
- **Danger:** critical red fill, for destructive actions only.
- **Disabled:** 50% opacity.

### Chips (state pills)
- **Style:** pill, 36px tall, 15px/600, tint background with the state colour text; a neutral pill uses the sunk fill.
- **Use:** counted states on the summary card ("2 normal", "1 urgent"); the triage word on a report, where it is uppercase with slight tracking in English.

### Cards / Containers
- **Corner Style:** 24px.
- **Background:** white.
- **Shadow Strategy:** card shadow (see Elevation).
- **Border:** none.
- **Internal Padding:** 20px; rows inside divided by 1px hairlines; facts sit in 16px-radius sunk wells, label over value.

### Inputs / Fields
- **Style:** a white pill with a 1px line outline, 52px tall, 20px entry text for phone and code; the country code sits in its own segment behind a divider. Free text uses a sunk, 20px-radius box.
- **Focus:** a 3px ink outline around the whole pill; boxed fields turn white on focus.
- **File picker:** the native control inside a dashed, sunk 20px well, its button a white shadowed pill.

### Navigation
- **Tab bar:** a floating white pill (float shadow) holding three items: icon (20px line icon, 2px stroke) plus label. Inactive items are ink-soft; hover fills sunk; the current page is filled ink black with white text.
- **Header:** one row on the ground, no band. Ringed brand mark (40px circle, white, 2px magenta ring, initial in magenta 800), "Namaste" in meta over the name in 18px/600, language toggle as a white pill whose selected half is filled black.
- **Report header:** a 48px white back circle beside the collected-on line.

### Summary Card (signature)
The home screen's first card: the display number, the date line in ink-soft under it, a wrapping row of counted state pills, the next step as a plain sentence, then a full-width black pill to open the report. Below it, three stat tiles (white, 20px radius, number over a meta label); the urgent count turns critical red, its label saying "urgent".

### Result Tiles
Each result is its own white tile on the ground, not a row in a table: name in ink-soft, the state word in its colour, the value at headline size with its unit in meta, the reference range in meta, and a range bar (8px track, the normal zone in translucent green, a 4px ink marker for the value). A critical result fills its tile with the critical tint.

### Chat Sheet
The last card on a report, styled as a bottom sheet (28px top radius, grab handle, float shadow). The patient's messages are black bubbles at the right; the assistant's are sunk-grey bubbles at the left, 20px radius, each with a small "who" label.

### Progress Steps
A list inside a card: a short state word column and the step text, divided by hairlines. The current step's word is a small black pill; done is green, stopped is red, later steps are ink-soft.

## Do's and Don'ts

### Do:
- **Do** put every action in an ink-black pill (52px tall, 999px radius); quiet grey for secondary, critical red only for destructive.
- **Do** pair every state colour with its word, on its tint, in a pill or as coloured bold text.
- **Do** separate cards from the mist ground with the card shadow and nothing else; separate rows inside with 1px divider hairlines.
- **Do** keep reading text at 17px and every tap target at 48px or more.
- **Do** show results as number tiles with the value large and the unit small.
- **Do** keep one language per screen and relax Devanagari headings to 1.35 line height with no tracking.

### Don't:
- **Don't** use magenta anywhere except the ring and initial of the brand mark.
- **Don't** use colour without a word: no bare dots, bars, or tinted rows that carry state alone.
- **Don't** add borders to cards or tinted header bands; the ground runs to the top.
- **Don't** build the blue-and-teal hospital portal: no icon-tile grids, no stock-photo doctor.
- **Don't** use 14px for anything the patient must read and act on.
