/**
 * Colour palettes the app ships. A palette is a set of theme-token values in
 * `globals.css` (selected by `data-palette` on <html>); light/dark mode is a
 * separate, per-device choice owned by next-themes. The user's palette is
 * saved to their account, mirroring the backend's `ThemePalette` enum.
 */
export const THEME_PALETTES = ['default', 'emerald'] as const;

export type ThemePalette = (typeof THEME_PALETTES)[number];
