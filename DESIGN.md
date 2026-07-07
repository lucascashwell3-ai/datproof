# Design — DATproof public dashboard

Single generated page (`site/index.html`, built by `scripts/build_site.py`). Self-contained:
inline CSS/JS/SVG; Google Fonts are the only external requests.

## Mood

"A rating agency's printed opinion, typeset with care" — white paper, black ink, one deep
seal-red. The wax stamp on the document, not the paint on the wall.

## Color (OKLCH throughout)

| Token | Value | Role |
|---|---|---|
| `--bg` | `oklch(1 0 0)` | page — pure white, no hidden warmth |
| `--surface` | `oklch(0.965 0.004 353)` | panels, table stripe |
| `--ink` | `oklch(0.20 0.015 353)` | body text (≥ 7:1 on bg) |
| `--muted` | `oklch(0.45 0.015 353)` | secondary text (≥ 4.5:1) |
| `--rule` | `oklch(0.85 0.008 353)` | hairlines |
| `--primary` | `oklch(0.45 0.16 353)` | seal red — brand moments, links, key rules; white text on fills |
| `--accent` | `oklch(0.42 0.10 255)` | ledger ink-blue — data marks, chart bars |

Status (severity) palette — badges always carry a text label, never color alone:
critical `oklch(0.34 0.15 353)` · high `oklch(0.50 0.15 15)` · medium `oklch(0.55 0.11 75)`
· low `oklch(0.45 0.02 255)`.

Strategy: **restrained** — neutrals + seal-red ≤ 10% of the surface. Dark mode: none (a
printed document is light; deliberate single-theme choice).

## Typography

- Display serif: **Newsreader** (opsz axis; true italics) — verdict, headings, masthead.
- Data/mono: **IBM Plex Mono** — every numeral, table figures (tabular by nature), as-of lines.
- UI sans: **IBM Plex Sans** — body prose, labels, badges.
- Verdict scale: `clamp(2rem, 6vw, 4.5rem)`, letter-spacing ≥ −0.02em, `text-wrap: balance`.
- Body measure ≤ 70ch.

## Layout

Document, not app shell: one column, max-width ~1080px, generous margins; hairline rules
separate sections (no card grids). Ledger table is full-bleed within the column. Chart is
inline SVG sized to the column. Print stylesheet included (it's a report — it should print).

## Motion

Quiet and purposeful: bars grow from the baseline once on load (transform-only, ~600ms
ease-out-quint, stagger 40ms); row/mark hover states; tooltip fade 120ms. All gated behind
`@media (prefers-reduced-motion: no-preference)`; the no-motion default is fully visible.

## Charts (see dataviz skill)

- Holdings by company → horizontal bars, single series in `--accent`, 4px rounded data-end
  anchored at baseline, 2px surface gaps, direct value labels, per-mark hover tooltip.
- Headline metrics → typographic stat row (ruled, not carded).
- No dual axes; no pie; severity colors never used for series.
