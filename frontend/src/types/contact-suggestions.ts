/**
 * Contact suggestions: participant emails integrations reported on at least
 * five of the user's journals that match no contact.
 *
 * Mirrors the JSON:API schemas under `/api/integrations/contact-suggestions`.
 */

import type {
  JsonApiCollectionResponse,
  JsonApiResource,
  JsonApiResponse,
} from '@/types/api';

export type ContactSuggestionAttributes = {
  email: string;
  /** The name integrations most often reported for the email. */
  display_name: string | null;
  /** How many journals the email was seen on. */
  event_count: number;
  /** Start of the most recent journal the email was seen on (ISO 8601). */
  last_seen_at: string;
};

export interface ContactSuggestionResource extends JsonApiResource<ContactSuggestionAttributes> {
  type: 'contact-suggestions';
}

export type ContactSuggestionListResponse =
  JsonApiCollectionResponse<ContactSuggestionResource>;

/** Accept into a new contact, or into an existing one. */
export type AcceptContactSuggestionTarget =
  | { kind: 'new'; first_name: string; last_name?: string | null }
  | { kind: 'existing'; contact_id: number };

export interface AcceptContactSuggestionRequest {
  data: {
    type: 'contact-suggestion-acceptances';
    attributes: {
      email: string;
      target: AcceptContactSuggestionTarget;
    };
  };
}

export type ContactSuggestionAcceptanceAttributes = {
  email: string;
  contact_id: number;
  /** Journals the contact was newly linked to. */
  linked_journal_count: number;
};

export interface ContactSuggestionAcceptanceResource extends JsonApiResource<ContactSuggestionAcceptanceAttributes> {
  type: 'contact-suggestion-acceptances';
}

export type ContactSuggestionAcceptanceResponse =
  JsonApiResponse<ContactSuggestionAcceptanceResource>;

export interface IgnoreContactSuggestionRequest {
  data: {
    type: 'ignored-contact-suggestions';
    attributes: { email: string };
  };
}

export type IgnoredContactSuggestionAttributes = {
  email: string;
  provenance: string;
  created_at: string | null;
};

export interface IgnoredContactSuggestionResource extends JsonApiResource<IgnoredContactSuggestionAttributes> {
  type: 'ignored-contact-suggestions';
}

export type IgnoredContactSuggestionListResponse =
  JsonApiCollectionResponse<IgnoredContactSuggestionResource>;
