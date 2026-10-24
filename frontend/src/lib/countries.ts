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

/**
 * Phone-numbering regions libphonenumber knows that are not ISO 3166-1
 * countries (Ascension Island, Tristan da Cunha, Kosovo). The backend checks
 * the default country against ISO 3166-1, so offering these would fail.
 */
const NOT_ISO_3166 = new Set(['AC', 'TA', 'XK']);

/** Every country, sorted by its name in `locale`. */
export function listCountries(locale = 'en'): Country[] {
  const names = new Intl.DisplayNames([locale], { type: 'region' });
  return getCountries()
    .filter(code => !NOT_ISO_3166.has(code))
    .map(code => ({ code, name: names.of(code) ?? code }))
    .sort((a, b) => a.name.localeCompare(b.name, locale));
}
