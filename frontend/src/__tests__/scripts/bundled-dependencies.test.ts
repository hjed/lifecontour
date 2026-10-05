/**
 * @jest-environment node
 */

import { readdirSync, readFileSync } from 'node:fs';
import path from 'node:path';

/**
 * scripts/third-party-notices.ts lists `pnpm licenses list --prod`, so a
 * package the app bundles but declares as a devDependency would ship with no
 * notice. Every package production source imports must be a dependency.
 */

const FRONTEND = path.resolve(__dirname, '../../..');
const SRC = path.join(FRONTEND, 'src');

const TEST_ONLY = /(__tests__|__mocks__|test-utils)\/|\.test\.|test-helpers\./;
const SOURCE_FILE = /\.(tsx?|css)$/;

// import x from 'p' · export … from 'p' · import 'p' · import('p') · require('p')
// and the CSS @import / @plugin that Tailwind compiles into the bundle
const SPECIFIER =
  /(?:^\s*import(?!\s+type\b)[^'"]*?from\s*|^\s*export[^'"]*?from\s*|^\s*import\s*|import\(\s*|require\(\s*|@import\s+|@plugin\s+)['"]([^'"]+)['"]/gm;

function productionSourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap(entry => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return productionSourceFiles(full);
    const relative = path.relative(SRC, full);
    return SOURCE_FILE.test(entry.name) && !TEST_ONLY.test(relative)
      ? [full]
      : [];
  });
}

function packageName(specifier: string): string | null {
  if (/^(\.|\/|@\/|node:)/.test(specifier)) return null;
  const [scopeOrName, name] = specifier.split('/');
  return scopeOrName.startsWith('@') ? `${scopeOrName}/${name}` : scopeOrName;
}

describe('bundled dependencies', () => {
  it('declares every package production source imports as a dependency', () => {
    const { dependencies } = JSON.parse(
      readFileSync(path.join(FRONTEND, 'package.json'), 'utf8')
    ) as { dependencies: Record<string, string> };

    const undeclared = new Set<string>();
    for (const file of productionSourceFiles(SRC)) {
      for (const [, specifier] of readFileSync(file, 'utf8').matchAll(
        SPECIFIER
      )) {
        const name = packageName(specifier);
        if (name && !(name in dependencies)) {
          undeclared.add(`${name} (${path.relative(FRONTEND, file)})`);
        }
      }
    }

    expect([...undeclared].sort()).toEqual([]);
  });
});
