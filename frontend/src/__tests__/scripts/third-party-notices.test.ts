/**
 * @jest-environment node
 */

import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import {
  findLicenceFiles,
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

describe('findLicenceFiles', () => {
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
    expect(findLicenceFiles(dir)).toEqual([path.join(dir, fileName)]);
  });

  it('finds every licence file a dual-licensed package ships, in name order', () => {
    writeFileSync(path.join(dir, 'LICENSE.Apache'), 'Apache');
    writeFileSync(path.join(dir, 'LICENSE'), 'MIT');
    expect(findLicenceFiles(dir)).toEqual([
      path.join(dir, 'LICENSE'),
      path.join(dir, 'LICENSE.Apache'),
    ]);
  });

  it('finds nothing when the package ships no licence file', () => {
    writeFileSync(path.join(dir, 'README.md'), 'readme');
    writeFileSync(path.join(dir, 'license-checker.js'), 'code');
    expect(findLicenceFiles(dir)).toEqual([]);
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

  it('reproduces every licence file, then every NOTICE file', () => {
    writeFileSync(path.join(dir, 'LICENSE'), 'MIT text');
    writeFileSync(path.join(dir, 'LICENSE.Apache'), 'Apache text');
    writeFileSync(path.join(dir, 'NOTICE'), 'Notice one');
    writeFileSync(path.join(dir, 'NOTICE.md'), 'Notice two');
    expect(readPackageNotices(dir)).toBe(
      'MIT text\n\nApache text\n\nNotice one\n\nNotice two'
    );
  });

  it('returns null when the package ships neither', () => {
    writeFileSync(path.join(dir, 'README.md'), 'readme');
    expect(readPackageNotices(dir)).toBeNull();
  });
});
