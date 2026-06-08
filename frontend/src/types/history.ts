/**
 * Entity-agnostic activity-history types matching backend API schemas.
 *
 * History is shared between domains (contacts, journals, ...). Each entry
 * records a field-level change with provenance. Contact-specific aliases are
 * re-exported from `types/contacts.ts` for backward compatibility.
 */

import { JsonApiLinks } from './api';

/** A single field-level change recorded in the history projection. */
export interface HistoryAttributes {
  entity_type: string;
  entity_id: number;
  field_name: string;
  old_value: string | null;
  new_value: string | null;
  changed_by: string | null;
  /** Provenance source value (ui, mcp, google_contacts, google_calendar, strava, immich, ...). */
  source: string;
  created_at: string | null;
}

/**
 * JSON:API resource for a history entry. `type` is intentionally a string
 * (e.g. `contact_history`, `journal_history`) so the resource is reusable
 * across entities.
 */
export interface HistoryResource {
  type: string;
  id: string;
  attributes: HistoryAttributes;
}

export interface HistoryPaginationMeta {
  total_count: number;
  page_count: number;
  current_page: number;
  per_page: number;
}

export interface HistoryListResponse {
  data: HistoryResource[];
  meta?: HistoryPaginationMeta;
  links?: JsonApiLinks;
}

/** Pagination filters accepted by history fetchers/hooks. */
export interface HistoryFilters {
  page?: number;
  limit?: number;
}
