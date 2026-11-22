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

import fs from 'node:fs';
import path from 'node:path';

import tailwindcss from '@tailwindcss/postcss';
import postcss from 'postcss';

/**
 * `@tailwindcss/node` registers a module-loader hook on import, which Jest 30.5+
 * forbids (the hook would attach to Jest's own loader, not the sandbox — see
 * jestjs/jest#16391). The hook only busts the ESM cache when a plugin is
 * reloaded, which a one-shot compile never does, so hide both registrars from
 * Tailwind. It feature-detects them, so this fails loudly if that changes.
 */
jest.mock('module', () => {
  const hookRegistrars = new Set(['register', 'registerHooks']);
  return Object.fromEntries(
    Object.entries(jest.requireActual<object>('module')).filter(
      ([key]) => !hookRegistrars.has(key)
    )
  );
});

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

/**
 * Status tokens. shadcn ships no success/warning/info colours, so the app
 * defines them alongside `destructive`; feature code uses these instead of
 * raw palette classes such as `text-green-600`.
 */
const STATUS_TOKEN_UTILITIES = [
  'bg-success',
  'text-success',
  'text-success-foreground',
  'border-success',
  'bg-warning',
  'text-warning',
  'text-warning-foreground',
  'border-warning',
  'bg-info',
  'text-info',
  'text-info-foreground',
];

/**
 * Radius steps the current shadcn styles use (e.g. Vega's pill badges).
 * Tailwind ships fixed-rem defaults for these; shadcn derives them from
 * `--radius` so the whole scale follows one knob.
 */
const DERIVED_RADII = ['2xl', '3xl', '4xl'];
const RADIUS_UTILITIES = DERIVED_RADII.map(step => `rounded-${step}`);

/** Probe for how the `dark:` variant compiles. */
const DARK_VARIANT_PROBE = 'dark:bg-primary';

const ALL_UTILITIES = [
  ...ANIMATION_UTILITIES,
  ...TYPOGRAPHY_UTILITIES,
  ...TOKEN_UTILITIES,
  ...STATUS_TOKEN_UTILITIES,
  ...RADIUS_UTILITIES,
  DARK_VARIANT_PROBE,
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

  describe('status theme tokens', () => {
    it.each(STATUS_TOKEN_UTILITIES)(EMITS_A_RULE, utility => {
      expect(emitsRule(css, utility)).toBe(true);
    });
  });

  describe('radius scale', () => {
    it.each(RADIUS_UTILITIES)(EMITS_A_RULE, utility => {
      expect(emitsRule(css, utility)).toBe(true);
    });

    it.each(DERIVED_RADII)('derives rounded-%s from --radius', step => {
      // `@theme inline` inlines the value into the utility itself.
      const start = css.indexOf(`.rounded-${step}`);
      const rule = css.slice(start, css.indexOf('}', start));
      expect(rule).toContain('calc(var(--radius)');
    });
  });

  describe('touch-target floor', () => {
    const source = fs.readFileSync(path.join(APP_DIR, 'globals.css'), 'utf8');

    it('raises controls to 40px on a coarse pointer only', () => {
      expect(css).toMatch(
        /@media \(pointer: coarse\)\s*\{\s*\.touch-target\s*\{\s*min-height: 2\.5rem/
      );
    });

    it("sits below utilities so a call site's own size wins", () => {
      // A floor in the utilities layer would be emitted after `min-h-11` and
      // shrink a 44px call site on phones.
      const layer = source.indexOf('@layer components');
      expect(layer).toBeGreaterThan(-1);
      expect(source.indexOf('.touch-target', layer)).toBeGreaterThan(layer);
    });
  });

  describe('dark variant', () => {
    /** The CSS Tailwind emits for the `dark:` probe, selector onwards. */
    function darkProbeRule(): string {
      const start = css.indexOf(String.raw`.dark\:bg-primary`);
      expect(start).toBeGreaterThan(-1);
      return css.slice(start, css.indexOf('}', start) + 1);
    }

    it('keys `dark:` off the `.dark` class that next-themes toggles', () => {
      // shadcn's standard: `@custom-variant dark (&:is(.dark *))`. Tailwind
      // v4's default is `prefers-color-scheme`, which follows the OS and
      // ignores the in-app Light/Dark toggle.
      expect(darkProbeRule()).toMatch(/:is\(\.dark \*\)/);
    });

    it('never compiles `dark:` to a prefers-color-scheme media query', () => {
      expect(css).not.toContain('prefers-color-scheme');
    });
  });

  describe('palettes', () => {
    const source = fs.readFileSync(path.join(APP_DIR, 'globals.css'), 'utf8');

    /** The custom properties a top-level block declares, name → value. */
    function declaredVars(selector: string): Map<string, string> {
      const start = source.indexOf(`\n${selector} {`);
      expect(start).toBeGreaterThan(-1);
      const body = source.slice(start, source.indexOf('\n}', start));
      return new Map(
        [...body.matchAll(/(--[\w-]+):\s*([^;]+);/g)].map(m => [m[1], m[2]])
      );
    }

    const LIGHT = ":root[data-palette='emerald']";
    const DARK = ":root.dark[data-palette='emerald']";
    /** Shared by every palette: status meaning and chart categories. */
    const SHARED = /^--(success|warning|info|chart-\d)/;

    it('gives Emerald light and dark the same variables', () => {
      expect([...declaredVars(DARK).keys()].sort()).toEqual(
        [...declaredVars(LIGHT).keys()].sort()
      );
    });

    it('overrides every palette colour the default palette defines', () => {
      const paletteColours = [...declaredVars(':root').keys()].filter(
        name => name !== '--radius' && !SHARED.test(name)
      );

      expect([...declaredVars(LIGHT).keys()].sort()).toEqual(
        paletteColours.sort()
      );
    });

    it('leaves status and chart colours to the default palette', () => {
      const overridden = [...declaredVars(LIGHT).keys()];

      expect(overridden.filter(name => SHARED.test(name))).toEqual([]);
    });

    it('lets Emerald dark outrank Emerald light whatever the order', () => {
      // (0,3,0) beats (0,2,0), so the light block can never leak into dark.
      expect(source.indexOf(DARK)).toBeGreaterThan(source.indexOf(LIGHT));
      expect(source.indexOf(LIGHT)).toBeGreaterThan(
        source.indexOf('\n.dark {')
      );
    });

    /** WCAG relative luminance of an `oklch(L C h)` token value. */
    function luminance(value: string): number {
      const match = /oklch\(([\d.]+) ([\d.]+) ([\d.]+)\)/.exec(value);
      expect(match).not.toBeNull();
      const [L, C, h] = match!.slice(1).map(Number);
      const a = C * Math.cos((h * Math.PI) / 180);
      const b = C * Math.sin((h * Math.PI) / 180);
      const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3;
      const m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3;
      const s = (L - 0.0894841775 * a - 1.291485548 * b) ** 3;
      const clamp = (x: number) => Math.min(Math.max(x, 0), 1);
      const r = clamp(4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s);
      const g = clamp(-1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s);
      const bl = clamp(-0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s);
      return 0.2126 * r + 0.7152 * g + 0.0722 * bl;
    }

    function contrast(a: string, b: string): number {
      const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
      return (hi + 0.05) / (lo + 0.05);
    }

    const DEFAULT_LIGHT = declaredVars(':root');
    const DEFAULT_DARK = new Map([...DEFAULT_LIGHT, ...declaredVars('.dark')]);
    const MODES = {
      'default light': DEFAULT_LIGHT,
      'default dark': DEFAULT_DARK,
      'emerald light': new Map([...DEFAULT_LIGHT, ...declaredVars(LIGHT)]),
      'emerald dark': new Map([...DEFAULT_DARK, ...declaredVars(DARK)]),
    };
    /** Text tokens on the surfaces they are drawn on (WCAG AA, 4.5:1). */
    const TEXT_ON_SURFACE: [text: string, surface: string][] = [
      ...['foreground', 'primary', 'muted-foreground', 'destructive'].flatMap(
        text =>
          ['background', 'card', 'popover'].map(
            surface => [text, surface] as [string, string]
          )
      ),
      ...['success', 'warning', 'info'].flatMap(text =>
        ['background', 'card'].map(
          surface => [text, surface] as [string, string]
        )
      ),
      ['primary-foreground', 'primary'],
      ['secondary-foreground', 'secondary'],
      ['accent-foreground', 'accent'],
      ['sidebar-primary-foreground', 'sidebar-primary'],
    ];

    describe.each(Object.entries(MODES))('%s', (_mode, vars) => {
      it.each(TEXT_ON_SURFACE)('keeps %s readable on %s', (text, surface) => {
        expect(
          contrast(vars.get(`--${text}`)!, vars.get(`--${surface}`)!)
        ).toBeGreaterThanOrEqual(4.5);
      });
    });

    it('ships the palette selectors in the compiled stylesheet', () => {
      expect(css).toMatch(/:root\[data-palette=['"]?emerald['"]?\]/);
      expect(css).toMatch(/:root\.dark\[data-palette=['"]?emerald['"]?\]/);
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
