/**
 * ISO 3166-1 alpha-2 countries with display names.
 *
 * The codes come from libphonenumber-js (already a dependency) and the names
 * from `Intl.DisplayNames`, so the list needs no hand-maintained table.
 */

import { getCountries } from 'libphonenumber-js';

export interface Country {
  readonly code: string;
  readonly name: string;
}

/** Every country, sorted by its name in `locale`. */
export function listCountries(locale = 'en'): Country[] {
  const names = new Intl.DisplayNames([locale], { type: 'region' });
  return getCountries()
    .map(code => ({ code, name: names.of(code) ?? code }))
    .sort((a, b) => a.name.localeCompare(b.name, locale));
}
