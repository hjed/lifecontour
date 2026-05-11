/**
 * External links API hooks.
 *
 * Provides TanStack Query hooks for fetching external system links
 * for journals and contacts.
 */

import { useQuery } from '@tanstack/react-query';

import { API_ENDPOINTS } from '@/lib/constants';
import type { ExternalLinksResponse } from '@/lib/external-links';

// Query Keys
export const externalLinkKeys = {
  journal: (journalId: string) =>
    ['journals', journalId, 'external-links'] as const,
  contact: (contactId: string) =>
    ['contacts', contactId, 'external-links'] as const,
};

// Fetch Functions
async function fetchJournalExternalLinks(
  journalId: string
): Promise<ExternalLinksResponse> {
  const response = await fetch(
    `${API_ENDPOINTS.JOURNALS.BY_ID(journalId)}/external-links`,
    {
      credentials: 'include',
    }
  );

  if (!response.ok) {
    throw new Error('Failed to fetch journal external links');
  }

  return response.json();
}

async function fetchContactExternalLinks(
  contactId: string
): Promise<ExternalLinksResponse> {
  const response = await fetch(
    `${API_ENDPOINTS.CONTACTS.BY_ID(contactId)}/external-links`,
    {
      credentials: 'include',
    }
  );

  if (!response.ok) {
    throw new Error('Failed to fetch contact external links');
  }

  return response.json();
}

// React Query Hooks

/**
 * Fetch external system links for a journal.
 */
export function useJournalExternalLinks(journalId: string) {
  return useQuery({
    queryKey: externalLinkKeys.journal(journalId),
    queryFn: () => fetchJournalExternalLinks(journalId),
    enabled: !!journalId,
    staleTime: 5 * 60 * 1000, // 5 minutes
  });
}

/**
 * Fetch external system links for a contact.
 */
export function useContactExternalLinks(contactId: string) {
  return useQuery({
    queryKey: externalLinkKeys.contact(contactId),
    queryFn: () => fetchContactExternalLinks(contactId),
    enabled: !!contactId,
    staleTime: 5 * 60 * 1000, // 5 minutes
  });
}
