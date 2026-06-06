import { useMemo } from 'react';
import { ContactResource, TagResource } from '@/types/contacts';

/**
 * Transformed contact data for display purposes
 */
export interface DisplayContact {
  id: string;
  name: string;
  first_name: string;
  last_name?: string;
  is_favourite: boolean;
  photo_url?: string | null;
  primary_email?: string;
  primary_phone?: string;
  tags: TagResource[];
  created_at: string;
  updated_at: string;
  // Optional search highlighting fields
  highlighted?: Record<string, string> | null;
  isSearchResult?: boolean;
  highlightedName?: string | null;
  highlightedEmail?: string | null;
  highlightedPhone?: string | null;
}

/**
 * Custom hook to transform contact data for display
 * Eliminates duplicate contact transformation logic across pages
 * Supports optional search highlighting for search results
 */
export function useDisplayContacts(
  contacts: ContactResource[] | undefined,
  shouldUseSearch = false
): DisplayContact[] {
  return useMemo(() => {
    if (!contacts) return [];

    return contacts.map(contact => {
      const highlighted = contact.meta?.highlighted as Record<
        string,
        string
      > | null;
      const isSearchResult = shouldUseSearch && !!highlighted;

      // Pre-compute highlighted text for performance
      const highlightedName =
        isSearchResult && highlighted
          ? (highlighted.first_name || contact.attributes.first_name) +
            (highlighted.last_name
              ? ` ${highlighted.last_name}`
              : contact.attributes.last_name
                ? ` ${contact.attributes.last_name}`
                : '')
          : null;

      return {
        id: contact.id,
        name: `${contact.attributes.first_name} ${contact.attributes.last_name || ''}`.trim(),
        first_name: contact.attributes.first_name,
        last_name: contact.attributes.last_name,
        is_favourite: contact.attributes.is_favourite || false,
        photo_url: contact.attributes.photo_url ?? null,
        primary_email: contact.attributes.contact_methods?.find(
          m => m.attributes.method_type === 'email' && m.attributes.is_primary
        )?.attributes.value,
        primary_phone: contact.attributes.contact_methods?.find(
          m => m.attributes.method_type === 'phone' && m.attributes.is_primary
        )?.attributes.value,
        tags: contact.relationships?.tags?.data || [],
        created_at: contact.attributes.created_at,
        updated_at: contact.attributes.updated_at,
        // Include search highlighting data when available
        highlighted,
        isSearchResult,
        highlightedName,
        highlightedEmail:
          isSearchResult && highlighted ? highlighted.email || null : null,
        highlightedPhone:
          isSearchResult && highlighted ? highlighted.phone || null : null,
      };
    });
  }, [contacts, shouldUseSearch]);
}
