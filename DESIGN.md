---
name: VeerIQ
description: A measured workspace for repairing damaged data while preserving later decisions.
colors:
  bg: "#0e0e10"
  bg-raised: "#151517"
  bg-sunken: "#111113"
  bg-overlay: "#1a1a1d"
  surface: "#151517"
  surface-2: "#232326"
  surface-3: "#303033"
  border: "rgb(255 255 255 / 0.08)"
  border-strong: "rgb(255 255 255 / 0.14)"
  scrim: "rgb(3 4 8 / 0.72)"
  text: "#f2f1ed"
  text-2: "#aaa9a7"
  text-3: "#aaa9a7"
  text-inverse: "#0e0e10"
  primary: "#e8602c"
  primary-hover: "#ff8050"
  focus: "#ff9467"
  layer-armoriq: "#ff9467"
  layer-grant: "#a9c4d0"
  layer-domain: "#e5c285"
  layer-approval: "#e5c285"
  layer-postgres: "#a3ccb3"
  layer-runtime: "#94a3b8"
  outcome-allow: "#a3ccb3"
  outcome-block: "#ffa185"
  outcome-hold: "#e5c285"
  outcome-unavailable: "#ff9467"
  outcome-neutral: "#94a3b8"
  outcome-info: "#a9c4d0"
  diff-bad: "#ffa185"
  diff-good: "#a3ccb3"
  diff-keep: "#a9c4d0"
  light-bg: "#f4f4f1"
  light-bg-raised: "#fafaf8"
  light-bg-sunken: "#e9e9e4"
  light-bg-overlay: "#fafaf8"
  light-surface: "#fafaf8"
  light-surface-2: "#e9e9e4"
  light-surface-3: "#d3d3cb"
  light-border: "#d3d3cb"
  light-border-strong: "#b6b6ac"
  light-scrim: "rgb(20 20 20 / 0.45)"
  light-text: "#202021"
  light-text-2: "#62625e"
  light-text-3: "#62625e"
  light-text-inverse: "#ffffff"
  light-primary: "#a7390e"
  light-primary-hover: "#b84113"
  light-focus: "#a7390e"
  light-layer-armoriq: "#a7390e"
  light-layer-grant: "#2c5465"
  light-layer-domain: "#795410"
  light-layer-approval: "#795410"
  light-layer-postgres: "#275c3c"
  light-layer-runtime: "#62625e"
  light-outcome-allow: "#275c3c"
  light-outcome-block: "#a02f17"
  light-outcome-hold: "#795410"
  light-outcome-unavailable: "#a7390e"
  light-outcome-neutral: "#62625e"
  light-outcome-info: "#2c5465"
  light-diff-bad: "#a02f17"
  light-diff-good: "#275c3c"
  light-diff-keep: "#2c5465"
typography:
  display:
    fontFamily: "Sunflower, sans-serif"
    fontSize: "64px"
    fontWeight: 500
    lineHeight: 1.08
    letterSpacing: "-.035em"
  body:
    fontFamily: "Geist, ui-sans-serif, system-ui, -apple-system, 'Segoe UI', sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: "-.003em"
  label:
    fontFamily: "Geist Mono, ui-monospace, monospace"
    fontSize: "10px"
    fontWeight: 400
rounded:
  control: "2px"
  surface: "2px"
spacing:
  shell-max: "1680px"
  header-height: "64px"
  mobile-gutter: "12px"
  desktop-gutter: "32px"
  content-top: "32px"
  small-gap: "8px"
  standard-gap: "16px"
  section-gap: "32px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.text-inverse}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
    padding: "12px 24px"
  button-secondary:
    backgroundColor: "{colors.bg-raised}"
    textColor: "{colors.text}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
    padding: "8px 12px"
  status-pill:
    textColor: "{colors.text-2}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
  navigation:
    textColor: "{colors.text-2}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
  panel:
    backgroundColor: "{colors.bg-raised}"
    textColor: "{colors.text}"
    rounded: "{rounded.surface}"
  objective-field:
    backgroundColor: "{colors.bg-sunken}"
    textColor: "{colors.text}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
    padding: "8px 12px"
  authority-boundary:
    backgroundColor: "{colors.bg-raised}"
    textColor: "{colors.text}"
    rounded: "{rounded.surface}"
---

# Design System: VeerIQ

## Overview

**Creative North Star: “The Recovery Workbench”**

VeerIQ is a focused operations workspace for repairing damaged records while keeping valid decisions made afterward. Its dark charcoal foundation, restrained orange actions, fine dividers, and compact evidence make the repair path easy to follow. The VeerIQ shield wordmark and Sunflower recovery headline carry the identity; the product remains visually distinct from the Flow State reference that informed its palette and type pairing.

Geist carries instructions and controls; Geist Mono marks identifiers, measurements, and technical evidence. The interface supports complete light and dark themes. Surfaces stay visually flat, with a consistent two-pixel corner treatment and restrained semantic colors that identify the enforcing layer or outcome. Live policy checks, scripted runs, local demo identities, and locally signed evidence are named in the interface so visual status does not overstate the source of a result.

**Key Characteristics:**

- Charcoal and mineral-paper themes share one semantic hierarchy.
- Warm orange marks primary actions and the ArmorIQ boundary layer.
- Sunflower headlines, Geist interface text, and Geist Mono metadata.
- Flat, finely divided surfaces with two-pixel corners.
- Recovery evidence foregrounds what is repaired and what must be preserved.

## Colors

The dark theme pairs near-black surfaces with warm orange and quiet defense-layer colors. Light mode switches the whole semantic palette to mineral paper and darker, readable accents. The frontmatter color keys retain the source names from `frontend/src/styles/tokens.css`; `light-*` entries describe the corresponding light-theme values.

### Primary

- **Signal Orange** (`primary`): primary actions and selected or emphasized interaction.
- **Warm Focus** (`focus`): visible keyboard focus and dark-theme accent text.
- **ArmorIQ Layer** (`layer-armoriq`): marks the outer policy boundary and its evidence.

### Secondary

- **Grant Blue** (`layer-grant`), **Domain Ochre** (`layer-domain`), **Approval Ochre** (`layer-approval`), **PostgreSQL Sage** (`layer-postgres`), and **Runtime Slate** (`layer-runtime`): identify independent enforcement layers. Their light-theme counterparts preserve the same meaning.

### Neutral

- **Workbench Charcoal** (`bg`), **Raised Charcoal** (`bg-raised`), **Sunken Charcoal** (`bg-sunken`), and **Overlay Charcoal** (`bg-overlay`) establish page, panel, inset, and overlay surfaces.
- **Warm Chalk** (`text`), **Instrument Gray** (`text-2`), and **Inverse Ink** (`text-inverse`) carry primary, secondary, and inverse text.
- **Fine Rule** (`border`) and **Strong Rule** (`border-strong`) separate regions without adding depth.
- **Mineral Paper** (`light-bg`), **Pale Panel** (`light-bg-raised`), **Inset Stone** (`light-bg-sunken`), and **Light Rule** (`light-surface-3`) form the corresponding light surfaces.

### Named Rules

**The Source-of-State Rule.** Use the current theme’s complete semantic variables together. Pair every decision or defense color with a readable label or icon; color alone does not carry the meaning.

## Typography

**Display Font:** Sunflower, sans-serif; bundled at weight 500.
**Body Font:** Geist, ui-sans-serif, system-ui, sans-serif; bundled at weights 400, 500, and 600.
**Label/Mono Font:** Geist Mono, ui-monospace, monospace; bundled at weight 400.

**Character:** Sunflower gives the recovery headline a distinct, human voice. Geist keeps dense operational instructions legible, while Geist Mono separates machine identifiers and measurements from prose.

### Hierarchy

- **Display** (500, 64px, 1.08 line-height): the Mission Control recovery headline; at 760px and below it becomes 44px.
- **Headline** (600, 24–30px): incident titles, page headings, and important recovery decisions.
- **Title** (600, 15–20px): panel and section headings.
- **Body** (400, 14px, 1.5 line-height): default interface text. Supporting explanations generally use 12–14px with relaxed leading.
- **Label** (400, 10–12px): Geist Mono for compact identifiers and evidence metadata; use uppercase only for short technical labels.

## Layout

The application shell and page content center within a 1680px maximum width. The sticky header is 64px high, with the VeerIQ shield lockup at left, system and identity controls at right, and navigation on a compact row that moves beneath the header at smaller widths. Main content begins with a two-column recovery introduction on wide screens and stacks on mobile. Mission Control places incident context and repair evidence before the scenario launcher, status strip, and recent runs. Run and approval views retain the same shared shell and reflow their evidence panels for narrow screens.

The established spacing uses compact 8px and 16px gaps, 32px section separation, and outer gutters that grow from 12px on narrow screens to 32px on desktop. The layout must let tables, event details, and action labels wrap or scroll within their own evidence regions rather than widening the page.

## Elevation & Depth

Visible work surfaces are flat. Page, raised, sunken, and overlay tones plus one-pixel borders establish hierarchy. The token file defines a pop shadow for isolated overlays, but connected work panels do not use shadows to imply importance. Motion is brief and state-linked; the global reduced-motion rule minimizes animation and transition duration.

**The Flat Evidence Rule.** Show relationships with shared dividers, tonal insets, and explicit labels. Keep cards and evidence panels visually connected to their section.

## Shapes

The global stylesheet caps the Tailwind rounded utility classes used by the interface at 2px. This keeps panels, controls, and evidence nearly square even where component markup uses rounded utility names. Small circular status dots and compact count badges are functional marks; they do not change the overall shape language. Borders are thin, and focus outlines remain clearly visible.

## Components

### Buttons

Actions are compact, high-contrast controls with simple color feedback.

- **Shape:** 2px corners, with sizes from 32px to 48px high.
- **Primary:** warm orange fill, theme-appropriate inverse text, and a stronger orange on hover.
- **Secondary:** raised or transparent surface with a visible line; hover shifts to the next surface tone.
- **Focus:** preserve the global 2px focus outline with a 2px offset.
- **Disabled:** lower opacity and a not-allowed cursor.

### Status and Defense Labels

Small badges and pills report system mode, run type, approval state, and the layer that made a decision. Keep the written state visible and use semantic color as a second cue. A live ArmorIQ check, a scripted planner, and local simulation must remain distinguishable in labels and explanatory text.

### Cards / Containers

Recovery, scenario, approval, and evidence panels use a raised surface, fine border, and the shared 2px corner. Use a shared divider when content belongs to one evidence group. Keep the panel heading compact and place secondary identifiers in muted or mono type. Large shadows and floating dashboard-card treatment are outside the implemented language.

### Inputs / Fields

Fields use the sunken or raised surface, a fine border, and readable text. Focus shifts the border or outline to the focus token. Preserve the visible field label and helper copy, particularly for approval scope and exact repair values.

### Navigation

The header uses Geist text links with a subtle raised background for the selected destination. At widths below the wide desktop breakpoint, navigation occupies its own row. The system indicator, theme switch, detail toggle, and local identity switcher remain available within the shell.

### Authority Boundary

The run view shows separate enforcement layers and the database as the final write boundary. Use one color per layer, then pair it with its layer name, current decision, and evidence. The database is described as durable PostgreSQL enforcement; local scripted and live service results stay explicitly labeled.

### Recorded Walkthrough

The `/walkthrough` is a six-stage replay of one actual run: Incident, Scope, Attempt, Boundary, Repair, and Proof. The selected run record is the source for each stage. Summarize incident truth in three plainly labeled rows: repaired changes, the blocked action and its decision source, and preserved or pending checks. Treat a pending check as pending; do not roll it into a preserved total.

### Boundary Story and Details

Tell the boundary story with visible plain-language labels for the source, decision, and effect. Keep `View run details` and other disclosure labels literal and easy to scan. Place technical identifiers and policy metadata inside the disclosure so readers can inspect the evidence without relying on color or deciphering abbreviations. Distinguish an SDK plan-binding refusal from a backend sponsor policy denial in both the label and explanation.

### Product Truth Footer

Keep the footer’s compact qualifiers visible: **Synthetic incident data · Local demo identities** and **Exact repair scope · Durable effects · Locally signed evidence**. Preserve the separate labels that identify scripted runs and local Ed25519 receipts so the interface never suggests a model or remote signer produced them.

## Do's and Don'ts

### Do:

- **Do** preserve both complete light and dark semantic themes.
- **Do** use Sunflower for the recovery headline, Geist for interface copy, and Geist Mono for technical metadata.
- **Do** keep the two-pixel shape treatment, fine dividers, and restrained orange action color.
- **Do** name the layer and written outcome wherever semantic colors appear.
- **Do** label scripted runs, local demo identities, and locally signed evidence clearly.
- **Do** keep durable PostgreSQL enforcement and the exact repair scope legible in run evidence.
- **Do** use the selected recorded run as the walkthrough source and keep repaired, preserved, and pending counts distinct.
- **Do** pair each boundary decision with its plain-language source and recorded effect; keep deeper identifiers behind a clearly named details disclosure.

### Don't:

- **Don't** present scripted or simulated enforcement as a live ArmorIQ decision.
- **Don't** present local demo identities as production authentication or local Ed25519 receipts as a remote signature.
- **Don't** imply that restoring a snapshot overwrites later changes; recovery repairs only the authorized damaged fields.
- **Don't** use color alone for allow, block, hold, or defense-layer state.
- **Don't** add large radii, pill-shaped work surfaces, or floating-card shadows to connected evidence.
- **Don't** imply ArmorIQ endorsement, certification, or universal injection resistance.
- **Don't** label SDK plan binding as a sponsor policy denial, or call a pending receipt check preserved.
