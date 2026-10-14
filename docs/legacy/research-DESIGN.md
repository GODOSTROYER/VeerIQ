---
name: VeerIQ
description: A measured research workspace with deliberate authority.
colors:
  bg: "#0e0e10"
  surface: "#151517"
  raised: "#1a1a1d"
  text: "#f2f1ed"
  muted: "#aaa9a7"
  line: "#303033"
  accent: "#e8602c"
  accent-text: "#ff9467"
  success: "#a3ccb3"
  deny: "#ffa185"
  hold: "#e5c285"
  btntext: "#0e0e10"
  soft-orange: "#e8602c0b"
  header: "#111113"
  light-bg: "#f4f4f1"
  light-surface: "#fafaf8"
  light-raised: "#e9e9e4"
  light-text: "#202021"
  light-muted: "#62625e"
  light-line: "#d3d3cb"
  light-accent: "#a7390e"
  light-success: "#275c3c"
  light-deny: "#a02f17"
  light-hold: "#795410"
  light-btntext: "#fff"
  light-soft-orange: "#a7390e09"
typography:
  display:
    fontFamily: "Sunflower, sans-serif"
    fontSize: "clamp(48px, 5.5vw, 78px)"
    fontWeight: 500
    lineHeight: 1.05
    letterSpacing: "-.035em"
  headline:
    fontFamily: "Sunflower, sans-serif"
    fontSize: "36px"
    fontWeight: 500
    lineHeight: 1.2
    letterSpacing: "-.03em"
  title:
    fontFamily: "Sunflower, sans-serif"
    fontSize: "23px"
    fontWeight: 500
    letterSpacing: "-.025em"
  body:
    fontFamily: "Geist, sans-serif"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.55
  panel-heading:
    fontFamily: "Geist, sans-serif"
    fontSize: "12px"
    fontWeight: 500
  button:
    fontFamily: "Geist, sans-serif"
    fontSize: "12px"
    fontWeight: 500
  input:
    fontFamily: "Geist, sans-serif"
    fontSize: "14px"
    lineHeight: 1.6
  label:
    fontFamily: "Geist Mono, monospace"
    fontSize: "10px"
    letterSpacing: ".08em"
  status:
    fontFamily: "Geist Mono, monospace"
    fontSize: "8px"
    letterSpacing: ".04em"
rounded:
  control: "2px"
  mode-badge: "3px"
spacing:
  icon-gap: "6px"
  control-gap: "8px"
  item-gap: "10px"
  action-gap: "14px"
  mobile-gutter: "20px"
  lane-inset: "21px"
  evidence-inset: "22px"
  container-inset: "25px"
  intro-gap: "60px"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.btntext}"
    typography: "{typography.button}"
    rounded: "{rounded.control}"
    padding: "11px 14px"
  button-primary-light:
    backgroundColor: "{colors.light-accent}"
    textColor: "{colors.light-btntext}"
    typography: "{typography.button}"
    rounded: "{rounded.control}"
    padding: "11px 14px"
  button-secondary:
    textColor: "{colors.text}"
    typography: "{typography.button}"
    rounded: "{rounded.control}"
    padding: "11px 14px"
  button-secondary-hover:
    backgroundColor: "{colors.raised}"
  button-text:
    textColor: "{colors.accent-text}"
    padding: "0"
  objective-input:
    textColor: "{colors.text}"
    typography: "{typography.input}"
    padding: "0"
    width: "100%"
  status-allow:
    textColor: "{colors.success}"
    typography: "{typography.status}"
    rounded: "{rounded.control}"
    padding: "3px 6px"
  status-deny:
    textColor: "{colors.deny}"
    typography: "{typography.status}"
    rounded: "{rounded.control}"
    padding: "3px 6px"
  status-hold:
    textColor: "{colors.hold}"
    typography: "{typography.status}"
    rounded: "{rounded.control}"
    padding: "3px 6px"
  panel:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
  decision-evidence:
    backgroundColor: "{colors.raised}"
    textColor: "{colors.text}"
    padding: "17px"
  boundary-scene:
    backgroundColor: "{colors.soft-orange}"
    height: "235px"
  navigation:
    padding: "28px 0"
---

# Design System: VeerIQ

## Overview

**Creative North Star: "The Protocol Workbench"**

VeerIQ feels like an instrument for useful research: a dark, measured workspace with clear type, fine rules, and a warm orange signal. The established direction deliberately recalls ArmorIQ's Flow State reference through charcoal, orange, and the Sunflower/Geist/Geist Mono pairing. VeerIQ retains its own wordmark and identity. This document describes the implementation; it does not establish endorsement or verify the reference site's current design.

Expressive display typography introduces the work; compact neutral typography carries the evidence. Depth comes from neighboring tones and visible boundaries. Motion illustrates an actual boundary decision rather than decorating the interface. The light theme preserves the same hierarchy with pale mineral surfaces and a darker orange accent.

**Key Characteristics:**

- Warm orange signals on restrained neutral surfaces.
- Sunflower headlines, Geist reading text, Geist Mono measurements.
- Flat panels connected by fine borders.
- Compact evidence with visible state labels and icons.
- Purposeful boundary motion with a reduced-motion still state.

## Colors

The palette pairs near-black charcoal with a warm orange accent; semantic decision colors remain quiet and readable. The frontmatter records the exact source values from `src/style.css`.

### Primary

- **Signal Orange** (`accent`): filled primary actions and selected navigation rules in the dark theme.
- **Readable Apricot** (`accent-text`): emphasized headline text, links, icons, and technical labels on dark surfaces.
- **Burnt Signal** (`light-accent`): both action fill and accent text in the light theme. The light theme's accent-text custom property uses this same value.
- **Orange Wash** (`soft-orange`, `light-soft-orange`): translucent emphasis behind the boundary scene, measured sink, and approval surface. Preserve the alpha channel.

### Neutral

- **Workbench Charcoal** (`bg`) and **Header Charcoal** (`header`): the page foundation and slightly lifted header.
- **Panel Charcoal** (`surface`) and **Evidence Charcoal** (`raised`): ordinary panels and inset evidence.
- **Warm Chalk** (`text`), **Instrument Gray** (`muted`), and **Fine Rule** (`line`): primary reading, secondary reading, and separators.
- **Dark Action Ink** (`btntext`): intentional dark text on the dark theme's orange primary action; do not swap it to white for visual familiarity.
- **Mineral Paper** (`light-bg`), **Pale Panel** (`light-surface`), and **Inset Stone** (`light-raised`): the light theme's corresponding tonal layers. Its header uses the light surface value.
- **Charcoal Ink** (`light-text`), **Stone Gray** (`light-muted`), **Pale Rule** (`light-line`), and **White Action Ink** (`light-btntext`): light-theme reading, separators, and primary-action text.
- **Allowed Sage** (`success`, `light-success`), **Denied Salmon / Brick** (`deny`, `light-deny`), and **Held Ochre** (`hold`, `light-hold`): semantic decision states. These are functional state colors, not additional brand accents.

**The Signal Role Rule.** Use filled accent for action and the separate accent-text role for reading on dark surfaces. Switch the full theme together rather than mixing dark and light roles.

## Typography

**Display Font:** Sunflower, with sans-serif fallback; the bundled face is weight (500).

**Body Font:** Geist, with sans-serif fallback; the source bundles weights (400), (500), and (600).

**Label/Mono Font:** Geist Mono, with monospace fallback; bundled weight (400).

**Character:** Sunflower gives short, decisive statements a distinctive silhouette. Geist makes the work readable, while Geist Mono gives identifiers, measurements, and decision labels a stable technical cadence.

### Hierarchy

- **Display:** the workspace headline uses the frontmatter's display role. At the mobile breakpoint it becomes (62px). The architecture headline uses (clamp(38px, 5vw, 72px)), line-height (1.1), and becomes (46px) on mobile.
- **Headline:** explanatory architecture statements use the headline role, becoming (32px) on mobile. Approval headings use Sunflower (26px), weight (500), tracking (-.025em), becoming (24px) on mobile.
- **Title:** scope statements use the title role. Inset decision headings use Sunflower (20px), weight (500), line-height (1.2).
- **Body:** intro copy uses the body role; most panel explanations use Geist (10–12px), with line-height (1.6–1.8). Mobile raises several evidence text roles by (1px). Architecture paragraphs use (14px); long research copy uses (13px). Keep these role-specific differences rather than flattening them into one size.
- **Panel heading / Button:** compact medium-weight Geist organizes the work and labels actions. Navigation uses (13px).
- **Label:** mono identifiers use the label role; compact metadata frequently overrides size to (8px). Boundary labels use (9px), tracking (.12em), and uppercase text.
- **Status:** the status role is uppercase, compact, and always accompanied by a decision word; it becomes (9px) on mobile.
- **Measurement:** the sink counter uses Sunflower (68px), weight (500), line-height (1.3), tracking (-.035em). Report effect estimates use (37px) and tracking (-.03em).

**The Three Voices Rule.** Use Sunflower for decisive statements and large results, Geist for reading and actions, and Geist Mono for measurements and technical metadata.

## Layout

Main content and footer share a centered maximum width (1512px) and desktop horizontal inset (4.1%). The header is (78px) tall; above (1500px), its padding aligns with the centered content using `max(4.1%, calc((100vw - 1388px)/2))`. The intro uses two columns (1fr / 1.07fr), a (60px) gap, and (55px 0 37px) vertical padding. The objective uses a flexible input plus a (254px) control column, with (28px) gap and (23px 25px) inset.

The operating surface is a connected grid (1.18fr / 1fr / .98fr), with shared outside borders and internal dividers. Each lane can grow with content; the grid has a minimum height (532px). Headings are (58px) high, usually with (21px) side inset. Evidence surfaces use (22px) side inset. The event list scrolls at a maximum height (690px), reducing to (500px) on mobile.

At (1100px) and below, header and main inset become (25px), the small Flow State lockup is hidden, and the work grid uses two columns. The evidence lane spans both and divides its contents into three columns. At (760px) and below, content inset becomes (20px), navigation moves to its own header row, the intro and objective stack, and all work lanes become one column. The boundary scene drops from (235px) to (184px). Approval controls become a two-column button row. Keep labels complete as content stacks; only the desktop-only mode suffix is hidden.

The spacing frontmatter is an extracted vocabulary of recurring gaps and insets, not a universal mathematical scale. Preserve the compact work density and larger separation around introductions and major sections.

## Elevation & Depth

There are no box shadows. Distinguish page, header, panels, and inset evidence through their tone, a single-pixel separator, or a low-opacity orange wash. Buttons react through brightness, a tonal background, or an underline, without lifting. The boundary canvas is a contained mechanism, not a glow or background decoration.

**The Flat Evidence Rule.** Separate evidence with tone and rules; do not add floating-card shadows to connected work surfaces.

## Shapes

Panels, inset evidence, chart bars, and the boundary scene are square. Primary and secondary controls and decision chips have small control rounding (2px); the mode badge is slightly softer (3px). Borders remain thin (1px). The only recurring circular mark is the small activity dot. Avoid turning compact labels and actions into pill shapes.

## Components

### Buttons

Compact, decisive controls use the button role and small control rounding. Primary and secondary buttons have minimum height (41px), inset (11px 14px), and icon gap (8px); the mobile objective action has minimum height (45px). Primary actions pair accent fill with the theme's intentional button ink. Hover applies `brightness(1.13)` when enabled. Secondary actions have a line-colored border and a raised-tone hover fill. Text actions use accent-text, size (10px), no inset, and underline on hover. Icon controls use an (8px) inset and muted color. Disabled controls use opacity (.55) and the not-allowed cursor. There is no custom pressed animation or transition.

All interactive components share a visible (2px) accent-text outline with offset (4px). Preserve this keyboard treatment in any new control.

### Decision Chips

Small rectangular outlined labels use Geist Mono, uppercase words, and decision icons. Their inset is (3px 6px), icon gap (5px), and letter spacing (.04em). Allow, deny, and hold use the semantic color roles; info uses muted. Chips communicate state and are not clickable filters. The tool list fixes their width to (61px), increasing to (67px) on mobile.

### Cards / Containers

Connected panels use surface tone and line-colored borders, without radius or shadow. Panel headings align a small icon and title on the left with mono metadata on the right. Ordinary panel content has role-specific insets; raised decision evidence uses (17px). Approval uses a soft orange wash, (25px) inset, and a dividing rule before its artifact and actions; mobile inset becomes (20px).

### Inputs / Fields

The objective textarea is an unfilled, borderless field inside the bordered objective container, with inherited text color, accent caret, no inset, vertical resizing, and minimum height (67px). Mobile uses text size (13px) and minimum height (110px). Its visible label remains above it. The optional agent select uses surface fill, text color, line border, and (4px) inset; its maximum width is (170px). Checkboxes use the accent role. Disabled inputs use native behavior; no separate error-field styling is established. Errors appear in the raised, denial-colored banner.

### Navigation

Navigation is a horizontal line of text controls, with muted default labels and full-text selected labels. The selected workspace or architecture item carries a (2px) accent rule on its bottom edge. Desktop gap is (30px), becoming (24px) at the intermediate breakpoint and (26px) on mobile. Mobile navigation spans a second header row with button inset (14px 0). External links retain a small arrow and underline on hover. There is no hover lift or animated tab transition.

### Protocol Boundary

A fine-bordered orange-wash canvas distinguishes agent proposal from execution at a line placed at (57%) of its width. Sparse orange particles and a horizontal path provide context. A small moving square reaches the boundary or continues through it according to the latest tool decision; a denial receives a stopped marker. Decision text and tool identity are ordinary positioned text above the canvas, not canvas-only information. The source animates over a (5000ms) cycle, caps pixel ratio at (2), and suspends drawing when outside view. Reduced motion produces a still diagram. Do not invent a success animation independent of actual decisions.

### Evidence and Reports

The sink number is large and quiet, with its unit in Geist on the same baseline. Neighboring mono counts and explanatory text clarify what is measured. The report uses a compact two-arm horizontal chart on raised tracks; neutral marks establish the first arm and accent marks the second. An orange effect estimate is accompanied by an interval, methodology, and visible synthetic-data note. Empty reports use short neutral bars and a written explanation, without pretending data exists.

## Do's and Don'ts

### Do:

- **Do** retain the charcoal/orange and Sunflower/Geist/Geist Mono brand commitments.
- **Do** resolve semantic custom properties for the active theme, including the primary action's intentional text color.
- **Do** separate related evidence with fine rules, tonal insets, and compact headings.
- **Do** pair decision color with a written state and icon.
- **Do** retain visible keyboard focus and the reduced-motion still boundary.
- **Do** let complete labels and content stack at the established responsive breakpoints.

### Don't:

- **Don't** replace dark primary-action text with white in the dark theme.
- **Don't** add shadows, large rounded cards, or pill controls to the established workbench.
- **Don't** use display type for dense explanations or mono type for ordinary reading.
- **Don't** create decorative motion that suggests a decision the runtime did not make.
- **Don't** make state depend on color alone or remove the focus outline.
- **Don't** imply official ArmorIQ identity, endorsement, or live verification through visual labels.
