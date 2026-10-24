/**
 * What integration imports left out of contacts, for the user to review
 * (#1820): today, a Google address whose AU/US/CA region names no state,
 * province or territory.
 *
 * Mirrors the JSON:API schemas under `/api/integrations/import-issues`.
 */

import type { JsonApiCollectionResponse, JsonApiResource } from '@/types/api';

export interface SkippedAddress {
  street_line_1: string;
  street_line_2: string | null;
  locality: string | null;
  region: string | null;
  postal_code: string | null;
  country_code: string;
}

export type ContactImportIssueAttributes = {
  contact_id: number;
  contact_name: string;
  /** The import that skipped it, e.g. `google`. */
  integration_source: string;
  kind: 'skipped_address';
  /** Why: `unrecognised_region` - its region names no state or province. */
  reason: string;
  address: SkippedAddress;
  /** When it was first skipped (ISO 8601). */
  created_at: string;
};

export interface ContactImportIssueResource extends JsonApiResource<ContactImportIssueAttributes> {
  type: 'contact-import-issues';
}

export type ContactImportIssueListResponse =
  JsonApiCollectionResponse<ContactImportIssueResource>;
