/**
 * @jest-environment node
 *
 * The design-sync kit is keyed to the frontend package name.
 *
 * `.design-sync/config.json` names the package (`pkg`) the previews import
 * from and the browser global (`globalName`) the bundle is published under.
 * Four places must agree: `package.json`, `config.json`, the preview imports
 * and the `window.<globalName>` samples the design agent reads. None of them is
 * type-checked — `.design-sync/` is a dot-directory `tsc` never includes — so a
 * rename that misses one only surfaces in the next re-sync. This reads the
 * files instead, following `src/app/__tests__/globals-css.test.ts`.
 */

import { readdirSync, readFileSync } from 'fs';
import { join, resolve } from 'path';

import { APP_NAME } from '@/lib/constants';

interface PackageJson {
  name: string;
  description: string;
  author: string;
}

interface DesignSyncConfig {
  pkg: string;
  globalName: string;
}

const FRONTEND_ROOT = resolve(__dirname, '../..');
const DESIGN_SYNC_DIR = join(FRONTEND_ROOT, '.design-sync');
const PREVIEWS_DIR = join(DESIGN_SYNC_DIR, 'previews');
const PREVIEW_COUNT = 47;
const RETIRED_PACKAGE = 'personal-management-frontend';
const RETIRED_GLOBAL = 'window.PMS';
const AGENT_FACING_DOCS = ['conventions.md', 'NOTES.md'];

function readJson<T>(path: string): T {
  return JSON.parse(readFileSync(path, 'utf8')) as T;
}

const packageJson = readJson<PackageJson>(join(FRONTEND_ROOT, 'package.json'));
const config = readJson<DesignSyncConfig>(join(DESIGN_SYNC_DIR, 'config.json'));

const previews = readdirSync(PREVIEWS_DIR)
  .filter(entry => entry.endsWith('.tsx'))
  .map(entry => ({
    name: entry,
    source: readFileSync(join(PREVIEWS_DIR, entry), 'utf8'),
  }));

describe('frontend package identity', () => {
  it('is named lifecontour-frontend', () => {
    expect(packageJson.name).toBe('lifecontour-frontend');
  });

  it('describes itself as the product', () => {
    expect(packageJson.description).toContain(APP_NAME);
  });

  it('names the real author', () => {
    expect(packageJson.author).toBe('Harry J E Day');
  });
});

describe('design-sync config', () => {
  it('targets the frontend package', () => {
    expect(config.pkg).toBe(packageJson.name);
  });

  it('publishes the bundle under the product name', () => {
    expect(config.globalName).toBe(APP_NAME);
  });
});

describe('design-sync previews', () => {
  it('covers every primary component', () => {
    expect(previews).toHaveLength(PREVIEW_COUNT);
  });

  it.each(previews.map(preview => [preview.name, preview.source]))(
    '%s imports the kit from the configured package',
    (_name, source) => {
      expect(source).toContain(`from '${config.pkg}'`);
      expect(source).not.toContain(RETIRED_PACKAGE);
    }
  );
});

describe('design-sync agent-facing docs', () => {
  it.each(AGENT_FACING_DOCS)(
    '%s refers to the bundle by its published global',
    doc => {
      const source = readFileSync(join(DESIGN_SYNC_DIR, doc), 'utf8');

      expect(source).toContain(`window.${config.globalName}`);
      expect(source).not.toContain(RETIRED_GLOBAL);
      expect(source).not.toContain(RETIRED_PACKAGE);
    }
  );
});
