/**
 * Colour palettes the app ships. A palette is a set of theme-token values in
 * `globals.css`, selected by `data-palette` on <html>; light/dark mode is a
 * separate, per-device choice owned by next-themes (the `.dark` class). The
 * user's palette is saved to their account, mirroring the backend's
 * `ThemePalette` enum, and mirrored to localStorage so the blocking <head>
 * script can paint it before React — and before the settings read — lands.
 */
export const THEME_PALETTES = ['default', 'emerald'] as const;

export type ThemePalette = (typeof THEME_PALETTES)[number];

export const DEFAULT_PALETTE: ThemePalette = 'default';

interface PaletteDetails {
  label: string;
  description: string;
  /**
   * Preview colours for the picker, light mode. They are literals because a
   * swatch has to show a palette that is not the one currently applied.
   */
  swatch: readonly [primary: string, accent: string, surface: string];
}

/** Picker copy for each palette; a new palette fails to type-check without it. */
export const PALETTE_DETAILS: Record<ThemePalette, PaletteDetails> = {
  default: {
    label: 'Default',
    description: 'Neutral greys that keep the focus on your content.',
    swatch: ['oklch(0.205 0 0)', 'oklch(0.97 0 0)', 'oklch(1 0 0)'],
  },
  emerald: {
    label: 'Emerald',
    description: 'Emerald accents on cool, mist-tinted surfaces.',
    swatch: [
      'oklch(0.508 0.118 165.612)',
      'oklch(0.963 0.002 197.1)',
      'oklch(1 0 0)',
    ],
  },
};

/** The attribute on <html> the `globals.css` palette blocks select on. */
export const PALETTE_ATTRIBUTE = 'data-palette';

/**
 * Browser-keyed mirror of the account's palette. Never the answer once the
 * settings read lands — the account wins — and cleared whenever no one is
 * signed in, so it cannot dress the next account in the previous one's colours.
 */
export const PALETTE_STORAGE_KEY = 'pms-theme-palette';

export function isThemePalette(value: unknown): value is ThemePalette {
  return (
    typeof value === 'string' &&
    (THEME_PALETTES as readonly string[]).includes(value)
  );
}

/** Paint `palette`; the default palette is the absence of the attribute. */
export function applyPalette(palette: ThemePalette): void {
  const root = document.documentElement;
  if (palette === DEFAULT_PALETTE) {
    root.removeAttribute(PALETTE_ATTRIBUTE);
  } else {
    root.setAttribute(PALETTE_ATTRIBUTE, palette);
  }
}

export function readCachedPalette(): ThemePalette {
  try {
    const cached = localStorage.getItem(PALETTE_STORAGE_KEY);
    return isThemePalette(cached) ? cached : DEFAULT_PALETTE;
  } catch {
    return DEFAULT_PALETTE;
  }
}

export function cachePalette(palette: ThemePalette): void {
  try {
    if (palette === DEFAULT_PALETTE) {
      localStorage.removeItem(PALETTE_STORAGE_KEY);
    } else {
      localStorage.setItem(PALETTE_STORAGE_KEY, palette);
    }
  } catch {
    // Storage unavailable (private mode, quota): the account still applies.
  }
}

/** Back to the default palette and no mirror — for when no one is signed in. */
export function resetPalette(): void {
  cachePalette(DEFAULT_PALETTE);
  applyPalette(DEFAULT_PALETTE);
}

/**
 * Inline, render-blocking script for the root layout's <head>: applies the
 * cached palette before first paint, as Next's "preventing flash before
 * hydration" guide does for themes. It only ever writes a value from
 * {@link THEME_PALETTES}, and swallows storage errors.
 */
export const PALETTE_BOOTSTRAP_SCRIPT = `(function(){try{var p=localStorage.getItem(${JSON.stringify(
  PALETTE_STORAGE_KEY
)});if(p!==${JSON.stringify(DEFAULT_PALETTE)}&&${JSON.stringify(
  THEME_PALETTES
)}.indexOf(p)!==-1){document.documentElement.setAttribute(${JSON.stringify(
  PALETTE_ATTRIBUTE
)},p);}}catch(e){}})();`;
