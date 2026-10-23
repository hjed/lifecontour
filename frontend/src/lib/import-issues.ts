/**
 * Wording for the addresses an import skipped, for review (#1820).
 */

import type { SkippedAddress } from '@/types/contact-import-issues';

/** What a country's regions are called, for the countries whose are checked. */
const REGION_KINDS: Record<string, string> = {
  AU: 'state or territory',
  US: 'state',
  CA: 'province or territory',
};

/** The address's lines that are set, as one line. */
export function describeAddress(address: SkippedAddress): string {
  const place = [address.region, address.postal_code].filter(Boolean).join(' ');
  return [address.street_line_1, address.street_line_2, address.locality, place]
    .filter(Boolean)
    .join(', ');
}

function countryName(code: string): string {
  try {
    return new Intl.DisplayNames(['en'], { type: 'region' }).of(code) ?? code;
  } catch {
    return code;
  }
}

/** Why the address was skipped, in a sentence. */
export function skippedReason(reason: string, address: SkippedAddress): string {
  const kind = REGION_KINDS[address.country_code];
  if (reason === 'unrecognised_region' && kind) {
    return `“${address.region}” isn’t a ${kind} of ${countryName(address.country_code)}`;
  }
  return 'It couldn’t be imported';
}
