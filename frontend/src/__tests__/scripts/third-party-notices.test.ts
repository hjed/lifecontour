/**
 * @jest-environment node
 */

import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import {
  findLicenceFile,
  readPackageNotices,
  renderThirdPartyNotices,
  type PnpmLicences,
} from '../../../scripts/third-party-notices';

const LICENCES: PnpmLicences = {
  MIT: [
    {
      name: 'zod',
      versions: ['4.1.0'],
      paths: ['/deps/zod'],
      license: 'MIT',
      homepage: 'https://zod.dev',
    },
    {
      name: 'no-licence-file',
      versions: ['1.0.0'],
      paths: ['/deps/no-licence-file'],
      license: 'MIT',
    },
  ],
  'Hippocratic-2.1': [
    {
      name: 'react-leaflet',
      versions: ['5.0.0'],
      paths: ['/deps/react-leaflet'],
      license: 'Hippocratic-2.1',
      homepage: 'https://react-leaflet.js.org',
    },
  ],
};

const LICENCE_TEXTS: Record<string, string> = {
  '/deps/zod': 'MIT License\n\nCopyright (c) Colin McDonnell',
  '/deps/react-leaflet': 'Hippocratic License Version 2.1',
};

const readLicenceText = (dir: string): string | null =>
  LICENCE_TEXTS[dir] ?? null;

describe('renderThirdPartyNotices', () => {
  const notices = renderThirdPartyNotices(LICENCES, readLicenceText);

  it('reproduces each package licence text under its name and version', () => {
    expect(notices).toContain(
      [
        'react-leaflet@5.0.0',
        'License: Hippocratic-2.1',
        'Homepage: https://react-leaflet.js.org',
        '',
        'Hippocratic License Version 2.1',
      ].join('\n')
    );
  });

  it('records the declared licence of a package that ships no licence file', () => {
    expect(notices).toContain(
      [
        'no-licence-file@1.0.0',
        'License: MIT',
        '',
        'No licence file is shipped with this package; its declared licence is MIT.',
      ].join('\n')
    );
  });

  it('lists packages in name order, whatever their licence', () => {
    const order = ['no-licence-file@', 'react-leaflet@', 'zod@'].map(entry =>
      notices.indexOf(entry)
    );
    expect(order).toEqual([...order].sort((a, b) => a - b));
    expect(order).not.toContain(-1);
  });
});

describe('findLicenceFile', () => {
  let dir: string;

  beforeEach(() => {
    dir = mkdtempSync(path.join(tmpdir(), 'notices-'));
  });

  afterEach(() => {
    rmSync(dir, { recursive: true, force: true });
  });

  it.each([
    'LICENSE',
    'LICENCE.md',
    'license.txt',
    'COPYING',
    'LICENSE-MIT.txt',
    'LICENSE.BSD',
  ])('finds %s', fileName => {
    writeFileSync(path.join(dir, 'package.json'), '{}');
    writeFileSync(path.join(dir, fileName), 'text');
    expect(findLicenceFile(dir)).toBe(path.join(dir, fileName));
  });

  it('returns null when the package ships no licence file', () => {
    writeFileSync(path.join(dir, 'README.md'), 'readme');
    writeFileSync(path.join(dir, 'license-checker.js'), 'code');
    expect(findLicenceFile(dir)).toBeNull();
  });
});

describe('readPackageNotices', () => {
  let dir: string;

  beforeEach(() => {
    dir = mkdtempSync(path.join(tmpdir(), 'notices-'));
  });

  afterEach(() => {
    rmSync(dir, { recursive: true, force: true });
  });

  it('appends a NOTICE file to the licence text', () => {
    writeFileSync(path.join(dir, 'LICENSE'), 'Apache License 2.0');
    writeFileSync(path.join(dir, 'NOTICE.txt'), 'Kobalte NOTICE');
    expect(readPackageNotices(dir)).toBe(
      'Apache License 2.0\n\nKobalte NOTICE'
    );
  });

  it('returns null when the package ships neither', () => {
    writeFileSync(path.join(dir, 'README.md'), 'readme');
    expect(readPackageNotices(dir)).toBeNull();
  });
});
