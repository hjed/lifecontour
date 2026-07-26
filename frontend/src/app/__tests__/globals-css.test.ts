/**
 * @jest-environment node
 */

/**
 * Compiles the app's real stylesheet and asserts that the utility classes the UI
 * depends on actually emit CSS.
 *
 * Tailwind v4 is configured entirely from `globals.css`. A missing `@import` or
 * `@plugin` there does not fail the build — Tailwind still *recognises* the
 * candidate, it simply has nothing to compile it to, so the class emits zero
 * bytes and the UI renders silently unstyled. That is how #1186
 * (`animate-in`/`animate-out` were no-ops across nine `ui/` primitives) and
 * #1178 both went unnoticed. These assertions are the tripwire.
 */

import path from 'node:path';

import tailwindcss from '@tailwindcss/postcss';
import postcss from 'postcss';

const APP_DIR = path.join(__dirname, '..');

/** Radix enter/exit transitions in the `ui/` primitives depend on these. */
const ANIMATION_UTILITIES = [
  'animate-in',
  'animate-out',
  'fade-in-0',
  'fade-out-0',
  'zoom-in-95',
  'zoom-out-95',
  'slide-in-from-right',
  'slide-out-to-left',
];

/** Emitted by the `@plugin '@tailwindcss/typography'` registration. */
const TYPOGRAPHY_UTILITIES = ['prose'];

/** Emitted from the `@theme inline` token block. */
const TOKEN_UTILITIES = [
  'bg-background',
  'text-foreground',
  'border-border',
  'bg-primary',
  'text-muted-foreground',
];

const ALL_UTILITIES = [
  ...ANIMATION_UTILITIES,
  ...TYPOGRAPHY_UTILITIES,
  ...TOKEN_UTILITIES,
];

/**
 * Runs `globals.css` through the same PostCSS plugin `postcss.config.cjs` hands
 * to Next, so what is asserted here is what ships.
 *
 * The entry point is virtual: PostCSS never reads `from` off disk, and Tailwind
 * uses it only as the base for resolving `@import`/`@plugin` specifiers. Placing
 * it alongside `globals.css` therefore reproduces the app's resolution exactly
 * without writing into the source tree.
 *
 * `@source inline(...)` forces the candidates to be generated, so the
 * assertions test the stylesheet rather than Tailwind's file scanner.
 */
async function compileStylesheet(candidates: readonly string[]) {
  const entry = [
    `@import './globals.css';`,
    `@source inline('{${candidates.join(',')}}');`,
  ].join('\n');

  const { css } = await postcss([tailwindcss()]).process(entry, {
    from: path.join(APP_DIR, 'globals-css.test.css'),
  });

  return css;
}

/**
 * True when the compiled output defines a rule for `className`. Tailwind
 * escapes CSS-special characters in selectors, so escape them here too.
 */
function emitsRule(css: string, className: string): boolean {
  const selector = className.replace(/[.:/[\]()%!<>@,+*~&#]/g, '\\$&');
  return new RegExp(`\\.${selector}[\\s,:.>{[]`).test(css);
}

const EMITS_A_RULE = 'emits a rule for %s';

describe('globals.css', () => {
  let css: string;

  beforeAll(async () => {
    css = await compileStylesheet(ALL_UTILITIES);
  }, 60_000);

  describe('enter/exit animations', () => {
    it.each(ANIMATION_UTILITIES)(EMITS_A_RULE, utility => {
      expect(emitsRule(css, utility)).toBe(true);
    });

    it.each(['enter', 'exit'])('defines the %s keyframes', name => {
      expect(css).toMatch(new RegExp(`@keyframes\\s+${name}\\s*\\{`));
    });
  });

  describe('typography plugin', () => {
    it.each(TYPOGRAPHY_UTILITIES)(EMITS_A_RULE, utility => {
      expect(emitsRule(css, utility)).toBe(true);
    });
  });

  describe('semantic theme tokens', () => {
    it.each(TOKEN_UTILITIES)(EMITS_A_RULE, utility => {
      expect(emitsRule(css, utility)).toBe(true);
    });
  });

  describe('no Tailwind v3 carry-overs', () => {
    it('never wraps a theme token in hsl()', () => {
      // The tokens are self-contained oklch values. `hsl(var(--token))` is a v3
      // contract that compiles to the invalid `hsl(oklch(...))` — see #1178.
      expect(css).not.toContain('hsl(var(--');
    });
  });
});
