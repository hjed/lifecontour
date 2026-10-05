/**
 * Writes public/third-party-notices.txt: the licence of every production npm
 * dependency, reproduced from the package's own licence file.
 *
 * Minified bundles drop licence headers (react-leaflet's Hippocratic notice
 * among them), so the app serves this file and links it beside "Source code".
 * Runs before `next dev` and `next build` (package.json predev/prebuild);
 * the output is generated, so it is gitignored.
 *
 * Plain TypeScript, run by Node's type stripping from a pnpm script:
 *   pnpm run prebuild
 */

import { execFileSync } from 'node:child_process';
import { readdirSync, readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';

/** One entry of `pnpm licenses list --json`; `versions[i]` lives at `paths[i]`. */
export interface PnpmLicencePackage {
  name: string;
  versions: string[];
  paths: string[];
  license: string;
  homepage?: string;
}

/** `pnpm licenses list --json` output, keyed by licence identifier. */
export type PnpmLicences = Record<string, PnpmLicencePackage[]>;

// LICENSE, LICENCE.md, COPYING, LICENSE-MIT.txt, LICENSE.BSD — not license-checker.js
const LICENCE_FILE = /^(licen[cs]e|copying)([.-][\w.-]*)?$/i;
const LICENCE_SOURCE = /\.(c?js|mjs|ts|json)$/i;
// Apache-2.0 requires a package's NOTICE to travel with it
const NOTICE_FILE = /^notice(\.(md|txt))?$/i;
const SEPARATOR = '='.repeat(78);

/** Every file in `dir` matching `pattern`, in code-unit name order. */
function findFiles(dir: string, pattern: RegExp): string[] {
  return readdirSync(dir)
    .filter(entry => pattern.test(entry) && !LICENCE_SOURCE.test(entry))
    .sort()
    .map(entry => path.join(dir, entry));
}

/** All of a package's licence files: a dual-licensed one ships several. */
export function findLicenceFiles(dir: string): string[] {
  return findFiles(dir, LICENCE_FILE);
}

/** The package's licence texts followed by its NOTICEs, or null if it ships none. */
export function readPackageNotices(dir: string): string | null {
  const texts = [...findLicenceFiles(dir), ...findFiles(dir, NOTICE_FILE)].map(
    file => readFileSync(file, 'utf8').trim()
  );
  return texts.length ? texts.join('\n\n') : null;
}

function renderEntry(
  pkg: PnpmLicencePackage,
  version: string,
  licenceText: string | null
): string {
  const header = [`${pkg.name}@${version}`, `License: ${pkg.license}`];
  if (pkg.homepage) header.push(`Homepage: ${pkg.homepage}`);
  const body =
    licenceText?.trim() ??
    `No licence file is shipped with this package; its declared licence is ${pkg.license}.`;
  return [...header, '', body].join('\n');
}

export function renderThirdPartyNotices(
  licences: PnpmLicences,
  readLicenceText: (dir: string) => string | null
): string {
  const entries = Object.values(licences)
    .flat()
    .flatMap(pkg =>
      pkg.versions.map((version, i) => ({
        key: `${pkg.name}@${version}`,
        text: renderEntry(pkg, version, readLicenceText(pkg.paths[i] ?? '')),
      }))
    )
    // Code-unit order, so the file is byte-identical whatever the build's locale
    .sort((a, b) => Number(a.key > b.key) - Number(a.key < b.key));

  const intro = [
    'THIRD-PARTY SOFTWARE NOTICES',
    '',
    'This web application bundles the following open-source packages.',
    'Each is listed with its licence, reproduced from the package itself.',
  ].join('\n');

  return (
    [intro, ...entries.map(entry => entry.text)].join(`\n\n${SEPARATOR}\n\n`) +
    '\n'
  );
}

/**
 * The pnpm that is running this hook, by absolute path (pnpm sets
 * npm_execpath for scripts), so nothing is resolved through PATH.
 */
function pnpmCommand(): [string, string[]] {
  const pnpm = process.env.npm_execpath;
  if (!pnpm) {
    throw new Error(
      'Run through pnpm (`pnpm run prebuild`): npm_execpath is unset'
    );
  }
  return /\.[cm]?js$/.test(pnpm) ? [process.execPath, [pnpm]] : [pnpm, []];
}

function main(): void {
  const frontendDir = path.resolve(import.meta.dirname, '..');
  const [command, prefix] = pnpmCommand();
  const args = [...prefix, 'licenses', 'list', '--prod', '--json'];
  const json = execFileSync(command, args, {
    cwd: frontendDir,
    encoding: 'utf8',
    maxBuffer: 64 * 1024 * 1024,
  });
  const notices = renderThirdPartyNotices(
    JSON.parse(json) as PnpmLicences,
    readPackageNotices
  );
  writeFileSync(
    path.join(frontendDir, 'public', 'third-party-notices.txt'),
    notices
  );
}

if (process.argv[1]?.endsWith(path.join('scripts', 'third-party-notices.ts'))) {
  try {
    main();
  } catch (error) {
    // predev passes --best-effort: a dev server (e.g. the dev Docker image,
    // whose pnpm store belongs to root) still starts without the notices.
    // prebuild does not, so a release image can never ship without them.
    if (!process.argv.includes('--best-effort')) throw error;
    console.warn(`third-party notices not generated: ${String(error)}`);
  }
}
