# Lifecontour Brand Guide

This directory holds the Lifecontour brand assets. They are part of the brand, not the code: the
AGPL licence that covers the code does not grant use of the name or the mark (see
[Trademark](#trademark)).

## The mark

An open logbook in line art:

- the **book** is the journal, the record of a life over time;
- the **person** on the left page is the people in it;
- the **creek** winding down the right page is the outdoors and the flow of life.

It is drawn by hand on a 64-unit grid with round caps and joins. The book outline is 4 units wide
and every stroke is at least 3 units, so the mark stays recognisable at 16px.

## Files

| File | Use |
|---|---|
| `mark.svg` | The mark in colour, on light backgrounds. The default. |
| `mark-dark.svg` | The mark on dark backgrounds. Same geometry, lightened strokes. |
| `mark-mono.svg` | Single colour, drawn in `currentColor`. For one-colour contexts. |
| `lockup.svg` | The mark and the "Lifecontour" wordmark, on light backgrounds. |
| `lockup-dark.svg` | The lockup on dark backgrounds. |

- The colour files set their colours in one `<style>` block through the `.book`, `.creek`,
  `.person` (and, in the lockups, `.wordmark`) classes. A light and a dark file differ only in that
  block, so a single `@media (prefers-color-scheme: dark)` rule can swap one for the other.
- `mark-mono.svg` follows the surrounding text colour only when the SVG is **inlined** in HTML. In
  an `<img>` there is no surrounding text colour, and it renders black.
- If you inline more than one of these files in the same page, rename their ids and scope their
  `<style>` selectors first. The variants share ids and class names, and an inlined `<style>`
  applies to the whole page.
- Every file has `role="img"` and a `<title>` of "Lifecontour", so assistive technology announces
  the name. An `<img>` of the mark still needs its own `alt` text.

### Showing the lockup in a README

GitHub picks an `<img>` SVG's colour scheme from the operating system, not from the GitHub theme,
so switch files with `<picture>`:

```html
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="branding/lockup-dark.svg">
  <img src="branding/lockup.svg" alt="Lifecontour" height="64">
</picture>
```

## Colour

| Token | Light (`mark.svg`) | Dark (`mark-dark.svg`) | Use |
|---|---|---|---|
| Eucalypt | `#2F5D50` | `#8CC7B2` | Book outline and wordmark (primary) |
| Creek | `#2B7A9E` | `#7CC4E4` | Creek line |
| Sandstone | `#D08A3C` | `#E8B27A` | Person (accent) |

Contrast, measured against white for the light tokens and against `#0D1117` (GitHub dark) for the
dark tokens:

- Light: Eucalypt 7.5:1, Creek 4.8:1, Sandstone 2.8:1.
- Dark: Eucalypt 9.9:1, Creek 9.8:1, Sandstone 10.0:1. The light Eucalypt is only 2.5:1 on dark,
  which is why the dark variant exists.
- **Sandstone is an accent only.** It falls below 3:1 on white, so never use it for text, and never
  let it be the only thing that carries meaning. The person reads by its shape, as the mono variant
  shows.

The palette belongs to the mark. The app keeps its neutral UI theme.

## Minimum size

- The mark: **16px**. Below that, use nothing rather than a blurred mark.
- The lockup: **120px wide**. Below that, the wordmark is illegible; use the mark alone.

## Clear space

Keep clear space of **one quarter of the mark's width** on every side: 16 units on the 64-unit
grid, or 4px around a 16px mark. Nothing else (text, other logos, frame edges) goes inside it. The
lockup's clear space is measured from the mark's width, not the lockup's.

## Do and don't

Do:

- use the files as they are, scaled uniformly;
- use `mark.svg` / `lockup.svg` on light backgrounds and the `-dark` files on dark ones;
- use `mark-mono.svg` where only one colour is available.

Don't:

- recolour the mark outside the palette, or mix light and dark tokens;
- stretch, skew, rotate or redraw it;
- add outlines, shadows, gradients or other effects;
- place the colour mark on busy imagery where the strokes lose contrast;
- re-typeset the wordmark in a live font, or change its spacing;
- add concentric rings, dot-infill or similar ornament (see below).

## Cultural review rule

The mark must avoid motifs associated with **Aboriginal and Torres Strait Islander art**. In
particular:

- **no concentric circles or rings**, the waterhole and campsite motif;
- **no dot-infill**.

These motifs carry cultural meaning and belong to their communities. A contour-ring variant of this
mark (concept E2) was rejected for this reason, and the same rule applies to any future variant,
illustration or icon built from the mark. A single circle, such as the person's head, is fine; rings
around a shared centre are not.

## Wordmark

- The typeface is **Inter SemiBold (600)**, the app's UI font, licensed under the
  [SIL Open Font License 1.1](https://openfontlicense.org/). The outlined letterforms are artwork
  made with the font, which the OFL permits.
- The source file is `@fontsource/inter@5.3.0`, `files/inter-latin-600-normal.woff`
  (`https://cdn.jsdelivr.net/npm/@fontsource/inter@5.3.0/files/inter-latin-600-normal.woff`).
- The text is converted to paths, so the lockup renders without the font:
  1. shape "Lifecontour" with HarfBuzz (`uharfbuzz`), which applies the font's kerning;
  2. draw each shaped glyph with fontTools' `SVGPathPen` at 40 units per em;
  3. start the pen at x = 76 with the baseline at y = 46.5. That leaves a visible gap of about 19
     units between the book and the "L", and centres the cap height on the mark.
- The cap height is 29 units, about 45% of the mark's 64-unit height.

## App icons

The app's `icon.svg`, `favicon.ico` and `apple-icon.png` are generated from `mark.svg` and
`mark-dark.svg`. The generation commands are recorded here when the app icons are added.

- `apple-icon.png` is padded by the clear-space rule (one quarter of the mark's width) on a light
  background.

## Trademark

The Lifecontour name and mark are not licensed under the AGPL. Forks may use the code but not the
name or the logo. See [`TRADEMARKS.md`](../TRADEMARKS.md).
