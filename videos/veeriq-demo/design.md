---
name: VeerIQ — The Line
colors:
  ink: "#0E0E10"
  ink-raised: "#151517"
  ink-panel: "#1A1A1D"
  bone: "#F2F1ED"
  ash: "#AAA9A7"
  signal: "#E8602C"
  signal-hot: "#FF8050"
  layer-armoriq: "#FF9467"
  layer-grant: "#A9C4D0"
  layer-domain: "#E5C285"
  layer-postgres: "#A3CCB3"
  diff-bad: "#FFA185"
  diff-good: "#A3CCB3"
fonts:
  display: "Instrument Serif"     # the human voice: statements, hero numerals
  machine: "Geist Mono"           # the machine voice: tool calls, logs, labels, HUD
  brand: "Sunflower"              # the VeerIQ wordmark only
radius: 2px
---

# VeerIQ — The Line

**Concept.** One vermillion line is the boundary, and it runs through the whole film doing a
different job in every scene: the incident timeline, the rewind playhead, the wire between the
gates, the trust boundary in the system diagram, the wall the agent hits, the link in the evidence chain, and finally the underline of the
VeerIQ wordmark. Every scene is the same line, changing its job.

## Colour

Taken from the VeerIQ app's dark theme (`frontend/src/styles/tokens.css`). Ink canvas in every
scene. One accent: `signal` (#E8602C), the app's primary. The four layer colours appear only as
small gate labels and bracket tints, exactly as the app uses them to name which layer decided.
`diff-bad` marks values that should not have come back; `diff-good` marks a correct repair.

## Type

Two voices that disagree on purpose, plus the brand mark:

- **Instrument Serif** speaks for people: the problem, the promise, the verdict, and every hero
  number. Display sizes 180–360px, tracking −0.035em, italic for the emotional half of a line.
- **Geist Mono** speaks for the machine: tool calls, receipts, hashes, labels, the HUD.
  Labels are uppercase, 20–26px, tracking +0.12em. Code is 30–40px.
- **Sunflower 500** is used only for the VeerIQ wordmark, as in the app.

The tension is the product's own: a persuasive sentence in a planted note (serif-like human
language) against a boundary that only reads tool names (mono).

## Motion

- Entrances decelerate (`expo.out`, `power4.out`); exits accelerate (`power3.in`) and are faster.
- Verdicts SLAM (0.12–0.2s) with a single impact frame; breathers hold still.
- The line draws with `expo.inOut` from its anchor; it never fades in.
- One slow camera drift per scene (≤3% scale); never the same ambient move twice in a row.
- Cuts land on the 120 BPM bar grid (2s bars). Velocity-matched exits and entrances meet at the cut.

## Texture and chrome

Fine film grain over the whole frame, a soft vignette, corner crop marks and a mono HUD
(project, section index, running timecode). Decoratives breathe; nothing is static.

## Don'ts

- No gradient text, no cyan or purple, no glassmorphism cards, no centred-everything layouts.
- No invented numbers. No claim that an ArmorIQ hold or approval was observed live.
