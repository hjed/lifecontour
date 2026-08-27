/**
 * @jest-environment node
 *
 * The placeholder home page is gone, and so is its fixture.
 *
 * ITER18-004 Phase 3 retired the six feature cards, their page test and the
 * `FEATURE_CARDS` fixture together, because a fixture left behind implies the
 * thing it describes still exists — the next person to open `test-utils` would
 * reasonably conclude the home page still renders a card grid.
 *
 * The type checker already catches an *import* of a removed export. What it
 * cannot catch is a copy of the same six strings reintroduced somewhere else,
 * so this reads the tree instead. It is a node-environment test that touches
 * the filesystem, following `src/app/__tests__/globals-css.test.ts`.
 */

import { readFileSync, readdirSync, statSync } from 'fs';
import { join, resolve } from 'path';

const RETIRED_FIXTURE = 'FEATURE_CARDS';
const FRONTEND_ROOT = resolve(__dirname, '../../..');
const SEARCHED_ROOTS = ['src', 'tests'];
const SEARCHED_EXTENSIONS = ['.ts', '.tsx'];
const IGNORED_DIRECTORIES = new Set([
  'node_modules',
  '.next',
  'ds-bundle',
  '.ds-sync',
]);

/** Every TypeScript source file under the searched roots. */
function sourceFiles(): string[] {
  const found: string[] = [];

  const walk = (directory: string) => {
    for (const entry of readdirSync(directory)) {
      if (IGNORED_DIRECTORIES.has(entry)) {
        continue;
      }
      const path = join(directory, entry);
      if (statSync(path).isDirectory()) {
        walk(path);
      } else if (SEARCHED_EXTENSIONS.some(ext => entry.endsWith(ext))) {
        found.push(path);
      }
    }
  };

  for (const root of SEARCHED_ROOTS) {
    walk(join(FRONTEND_ROOT, root));
  }

  return found;
}

describe('the retired placeholder fixture', () => {
  const files = sourceFiles();

  it('finds source files to search, so a silent empty sweep cannot pass', () => {
    expect(files.length).toBeGreaterThan(100);
  });

  it('is no longer declared in the shared test utilities', () => {
    const testUtils = readFileSync(
      join(FRONTEND_ROOT, 'src/test-utils/index.tsx'),
      'utf8'
    );

    expect(testUtils).not.toContain(RETIRED_FIXTURE);
  });

  it('has no remaining references anywhere under src or tests', () => {
    // This file is the one legitimate mention: it is the sweep itself.
    const referencing = files.filter(
      file =>
        file !== __filename &&
        readFileSync(file, 'utf8').includes(RETIRED_FIXTURE)
    );

    expect(referencing).toEqual([]);
  });

  it('leaves no placeholder page test behind', () => {
    const placeholderTests = files.filter(file =>
      file.endsWith(join('src', '__tests__', 'app', 'page.test.tsx'))
    );

    expect(placeholderTests).toEqual([]);
  });
});
