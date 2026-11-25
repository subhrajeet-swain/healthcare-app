---
name: Prime Healthcare
description: Patient lab-report app that reads like a medicine strip the patient already trusts.
colors:
  band-magenta: "#9c1458"
  band-ink: "#ffffff"
  foil: "#e7e9ec"
  foil-raised: "#f7f8f9"
  ink: "#14181f"
  ink-hover: "#2b313b"
  ink-soft: "#4a515c"
  hairline: "#b9bec5"
  perforation: "#8c939d"
  state-normal: "#0f6b5c"
  state-normal-tint: "#e6f2ef"
  state-attention: "#a33c08"
  state-attention-tint: "#fbefe7"
  state-critical: "#b3122e"
  state-critical-deep: "#8f0e25"
  state-critical-tint: "#fbe8eb"
typography:
  display:
    fontFamily: "Barlow Condensed, Noto Sans, sans-serif"
    fontSize: "2.5rem"
    fontWeight: 700
    lineHeight: 1
    letterSpacing: "0.03em"
  headline:
    fontFamily: "Barlow Condensed, Noto Sans, sans-serif"
    fontSize: "1.75rem"
    fontWeight: 700
    lineHeight: 1
    letterSpacing: "0.02em"
  title:
    fontFamily: "Barlow Condensed, Noto Sans, sans-serif"
    fontSize: "1.375rem"
    fontWeight: 700
    lineHeight: 1.1
    letterSpacing: "0.03em"
  body:
    fontFamily: "Noto Sans, Noto Sans Devanagari, sans-serif"
    fontSize: "1.0625rem"
    fontWeight: 400
    lineHeight: 1.5
    fontFeature: "tnum"
  label:
    fontFamily: "Barlow Condensed, Noto Sans, sans-serif"
    fontSize: "1.125rem"
    fontWeight: 700
    lineHeight: 1
    letterSpacing: "0.06em"
  meta:
    fontFamily: "Noto Sans, Noto Sans Devanagari, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 600
    letterSpacing: "0.06em"
rounded:
  none: "0"
spacing:
  "1": "4px"
  "2": "8px"
  "3": "12px"
  "4": "16px"
  "5": "24px"
  "6": "32px"
  "7": "48px"
components:
  button-primary:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.band-ink}"
    typography: "{typography.label}"
    rounded: "{rounded.none}"
    padding: "0 24px"
    height: "48px"
  button-primary-hover:
    backgroundColor: "{colors.ink-hover}"
  button-quiet:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    rounded: "{rounded.none}"
    padding: "0 24px"
    height: "48px"
  button-quiet-hover:
    backgroundColor: "{colors.foil}"
  button-danger:
    backgroundColor: "{colors.state-critical}"
    textColor: "{colors.band-ink}"
    typography: "{typography.label}"
    rounded: "{rounded.none}"
    padding: "0 24px"
    height: "48px"
  button-danger-hover:
    backgroundColor: "{colors.state-critical-deep}"
  strip:
    backgroundColor: "{colors.foil-raised}"
    rounded: "{rounded.none}"
    padding: "16px"
  input-text:
    backgroundColor: "{colors.band-ink}"
    textColor: "{colors.ink}"
    rounded: "{rounded.none}"
    padding: "0 12px"
    height: "48px"
  band:
    backgroundColor: "{colors.band-magenta}"
    textColor: "{colors.band-ink}"
    typography: "{typography.headline}"
    padding: "24px 16px 16px"
  next-tag:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.band-ink}"
    rounded: "{rounded.none}"
    padding: "4px 8px"
---

# Design System: Prime Healthcare

## Overview

**Creative North Star: "The Chemist Strip"**

A lab report should read like the blister strip of medicine an Indian patient already keeps in a kitchen drawer: printed foil, square cuts, dashed perforations between pockets, and a printed batch panel with the facts. The system is quiet foil grey with ink type, one saturated magenta product band at the top of every screen, and condensed uppercase headings that read like pharmacy print. It refuses the rounded-card-with-status-chip health app.

Density is calm and mobile-first (a single 40rem column, designed at 390px). Body text is set large (17px) for older readers and family caregivers, every target is at least 48px, and the whole interface runs in one chosen language, English or Hindi (Devanagari), picked once from the band and remembered on the device; Hindi is a first-class language, not a translation afterthought. Depth comes from the hairline-and-perforation system, never from shadow or rounding.

**Key Characteristics:**
- Foil grey ground, raised foil strips, ink type; magenta only on the product band and selection.
- Square corners everywhere (radius 0).
- One container, the strip: hairline outline, sections divided by dashed perforations.
- Barlow Condensed uppercase for headings, buttons and labels; Noto Sans and Noto Sans Devanagari for reading text.
- Tabular numerals throughout.
- State is always a word plus a colour, never colour alone.

## Colors

A cool, near-neutral foil palette with one magenta brand voice and a reserved three-state result scale.

### Primary
- **Strip Magenta** (band-magenta): the product band at the top of every screen, text selection, and the input caret. 7.9:1 with white. Never used for buttons or body content.

### Tertiary (result states)
- **Pharmacy Green** (state-normal) on its tint: the "normal" result state. Defined and reserved for result cells; not yet rendered in phase 0.
- **Burnt Orange** (state-attention) on its tint: the "attention" result state. Reserved like green. This shipped value is darker than the direction contract's orange; the build wins.
- **Critical Red** (state-critical), with a deeper hover (state-critical-deep) and tint: critical results, error messages, and destructive actions (delete-my-data).

### Neutral
- **Foil** (foil): page ground, and the quiet-button hover fill.
- **Raised Foil** (foil-raised): strip and info-message surfaces.
- **Ink** (ink): all text, the primary button, field borders, focus outlines, and the Next tag.
- **Ink Hover** (ink-hover): primary button hover.
- **Soft Ink** (ink-soft): ledes, hints, batch-panel labels. 6.2:1 on foil.
- **Hairline** (hairline): the one solid border: strip outlines, batch-panel cell dividers, phone-prefix divider.
- **Perforation** (perforation): dashed 1px dividers between sections inside a strip.
- **Paper White** (band-ink): text on the band, on ink and on red; the input field fill.

### Named Rules
**The Word-State Rule.** A result state is always carried by a printed word ("Normal", "Problem"), with colour as reinforcement. Colour alone never signals state.

**The One Band Rule.** Magenta appears as the product band and nowhere else that carries meaning. It is brand, not an action colour; actions are ink.

## Typography

**Display Font:** Barlow Condensed 600/700 (with Noto Sans, sans-serif), self-hosted.
**Body Font:** Noto Sans variable (with Noto Sans Devanagari, sans-serif), self-hosted.

**Character:** Condensed uppercase print against a humanist sans: pharmacy-label authority on top, plain readable text below, with Devanagari matched to the body face.

### Hierarchy
- **Display** (700, 2.5rem, 1.0, uppercase, 0.03em): the page heading (h1), one per screen.
- **Headline** (700, 1.75rem, 1.0, uppercase, 0.02em): the product name in the band.
- **Title** (700, 1.375rem, 1.1): strip titles and h2.
- **Body** (400, 1.0625rem, 1.5, tabular numerals): all reading text; ledes and strip paragraphs held to a 34rem measure.
- **Label** (700, 1.125rem, uppercase, 0.06em, display face): buttons; message prefixes ("Problem") use the same face at 1rem.
- **Meta** (600, 0.875rem, uppercase, 0.06em, text face): batch-panel labels such as Phone, Consent, Purpose, Version.

### Named Rules
**The One-Language Rule.** A screen speaks one language at a time: the one chosen with the English | हिंदी switch in the band (stored on the device, sets `<html lang>`). Hindi is set at the same size as English and never shrunk into a caption. Devanagari headings drop the uppercase display face and use Noto Sans Devanagari. Test names stay in English as the lab prints them ("आपका Hemoglobin 11.3 g/dL है"), in Hindi too: they match the paper report and the doctor's words, and a transliteration would be a second name for the same test. Numbers use Indian digit grouping (2,45,000) in both languages.

**The 17px Floor Rule.** Reading text never drops below 1.0625rem; only batch labels and meta reach 0.875rem.

## Layout

Single centered column, max 40rem, 16px side gutter; main has 32px top and 48px bottom padding. The band row shares the same column so the product name aligns with content. Spacing runs on a 4px base (4, 8, 12, 16, 24, 32, 48). Strips stack with 24px between them. Action rows wrap with 12px gaps, and below 30rem every button in an action row goes full width. The batch panel is an auto-fit grid of cells at least 8rem wide, so facts sit side by side on phone and desktop alike.

## Elevation & Depth

Flat. There are no shadows anywhere. Depth is expressed as print: the raised foil tone of a strip against the foil ground, a 1px hairline outline, and dashed perforations between sections inside it.

### Named Rules
**The Printed-Not-Lifted Rule.** Nothing floats. A surface is distinguished by tone and line, never by box-shadow.

## Shapes

Strips are cut square: radius is 0 on every surface, button and field. Borders come in exactly three kinds: 1px solid hairline (outlines and cell dividers), 1px dashed perforation (section breaks inside a strip), and 2px solid ink (buttons and input wells). Focus is a 3px solid ink outline offset 3px, switching to white on the magenta band.

## Components

### Buttons
Heavy, printed, unmistakable.
- **Shape:** square (0), 2px ink border, minimum 48px high, 24px horizontal padding.
- **Primary:** ink fill, white uppercase condensed label; hover lightens to ink-hover over 160ms (cubic-bezier(0.16, 1, 0.3, 1)).
- **Quiet:** transparent fill, ink border and text; hover fills with foil. On the band it inverts to white border and text with a 12% white hover wash.
- **Danger:** critical-red fill and border, used only for irreversible deletion; hover deepens.
- **States:** disabled at 0.55 opacity; aria-busy shows a progress cursor and a verb in progress ("Saving…").
- **Link button:** underlined plain text at full tap height, for secondary escapes such as changing the phone number.

### Cards / Containers (the Strip)
- **Corner Style:** square.
- **Background:** raised foil.
- **Shadow Strategy:** none (see Elevation).
- **Border:** 1px hairline outline; sections inside divided by 1px dashed perforation.
- **Internal Padding:** 16px; head row 12px by 16px with the title on the baseline.
- **Batch panel:** a definition-list footer row of cells divided by hairlines, uppercase meta labels over plain values; the strip's "facts" panel.
- **Perforated list:** list items separated by dashed perforations.
- **Next-step line:** a hairline-topped row at the strip foot: an ink "Next" tag followed by the one action the patient should expect.

### Inputs / Fields
- **Style:** a white well with a 2px ink border, square; text at 1.25rem with 0.04em tracking. The phone field carries a fixed +91 prefix cell divided by a hairline.
- **Focus:** the well (not the input) takes the 3px ink focus outline via focus-within.
- **Label and hint:** 600-weight label above, soft-ink hint below, linked by aria-describedby.

### Messages
- **Error:** critical-tint fill, critical border and text, prefixed with an uppercase condensed word ("Problem").
- **Info:** raised foil with a hairline border.

### Navigation (the Band)
The magenta band heads every screen: PRIME HEALTHCARE in the headline style, a greeting line in the chosen language with the English | हिंदी switch to its right (a bordered two-cell toggle, white on magenta, the chosen cell filled white), and at most one quiet button (Sign out, All reports) at the right of the name. The bottom tab nav and the per-result cell strip from the direction sketch are not built yet; document them when they ship.

## Do's and Don'ts

### Do:
- **Do** put every grouped piece of content in a strip and divide its sections with dashed perforations, not with gaps or new boxes.
- **Do** pair each state colour with a printed word.
- **Do** show one language per screen, from the band switch, with Hindi at full body size.
- **Do** keep every interactive target at least 48px tall.
- **Do** use ink for actions and reserve magenta for the band.
- **Do** keep numerals tabular.

### Don't:
- **Don't** round corners; radius is 0 everywhere.
- **Don't** use box-shadow for depth.
- **Don't** signal a result state by colour alone.
- **Don't** use magenta as a button or link colour.
- **Don't** set reading text below 17px.
