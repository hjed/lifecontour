/**
 * @jest-environment node
 */

/**
 * Feature code colours through theme tokens (`text-success`, `bg-destructive`,
 * `bg-muted`, ...) so a palette or mode switch reaches every screen. A raw
 * Tailwind palette class such as `text-green-600` is fixed: it ignores both
 * the palette and the Light/Dark toggle, and needs a hand-written `dark:`
 * twin to stay readable. This scan keeps them from creeping back in.
 *
 * Data colours (user-chosen calendar/tag hex values) and brand colours are
 * inline styles or constants, not palette classes, so they are unaffected.
 */

import fs from 'node:fs';
import path from 'node:path';

const SRC_DIR = path.join(__dirname, '..', '..');

const PALETTES = [
  'red',
  'orange',
  'amber',
  'yellow',
  'lime',
  'green',
  'emerald',
  'teal',
  'cyan',
  'sky',
  'blue',
  'indigo',
  'violet',
  'purple',
  'fuchsia',
  'pink',
  'rose',
  'slate',
  'gray',
  'zinc',
  'neutral',
  'stone',
].join('|');

/** `text-green-600`, `hover:bg-red-50`, `fill-yellow-400/50`, ... */
const RAW_PALETTE_CLASS = new RegExp(
  String.raw`(?<![\w-])(?:[\w-]+:)*(?:bg|text|border|ring|fill|stroke|outline|decoration|from|via|to|divide|shadow)-(?:${PALETTES})-\d{2,3}\b`
);

function sourceFiles(dir: string): string[] {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap(entry => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      return entry.name === '__tests__' ? [] : sourceFiles(full);
    }
    const isSource = /\.(tsx?|css)$/.test(entry.name);
    const isTest = /\.test\.tsx?$/.test(entry.name);
    return isSource && !isTest ? [full] : [];
  });
}

describe('feature code colours through theme tokens', () => {
  it('uses no raw Tailwind palette classes', () => {
    const offenders = sourceFiles(SRC_DIR).flatMap(file =>
      fs
        .readFileSync(file, 'utf8')
        .split('\n')
        .flatMap((line, index) => {
          const match = RAW_PALETTE_CLASS.exec(line);
          return match
            ? [`${path.relative(SRC_DIR, file)}:${index + 1} ${match[0]}`]
            : [];
        })
    );

    expect(offenders).toEqual([]);
  });
});
