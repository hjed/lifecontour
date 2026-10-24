/**
 * Contact import issues: what integration imports left out of contacts, for
 * the user to review (#1820). Each can be dismissed; one fixed at the source
 * clears on the next sync by itself.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { JsonApiErrorResponse } from '@/types/api';
import type { ContactImportIssueListResponse } from '@/types/contact-import-issues';
import { invalidateAfterMutation } from './invalidate-after-mutation';

const BASE_URL = '/api/integrations/import-issues';

export const contactImportIssueKeys = {
  all: ['contact-import-issues'] as const,
  list: (contactId?: string) =>
    [...contactImportIssueKeys.all, 'list', contactId ?? 'all'] as const,
};

async function request<T>(
  url: string,
  failureMessage: string,
  init: RequestInit = {}
): Promise<T> {
  const response = await fetch(url, { credentials: 'include', ...init });
  if (!response.ok) {
    const errorData: Partial<JsonApiErrorResponse> = await response
      .json()
      .catch(() => ({}));
    throw new Error(errorData.errors?.[0]?.detail || failureMessage);
  }
  return (response.status === 204 ? undefined : await response.json()) as T;
}

/** The user's pending issues, or one contact's when `contactId` is given. */
export function fetchContactImportIssues(
  contactId?: string
): Promise<ContactImportIssueListResponse> {
  const query = contactId ? `?contact_id=${encodeURIComponent(contactId)}` : '';
  return request(`${BASE_URL}${query}`, 'Failed to load skipped addresses');
}

export function dismissContactImportIssue(issueId: string): Promise<void> {
  return request(
    `${BASE_URL}/${encodeURIComponent(issueId)}/dismiss`,
    'Failed to dismiss the skipped address',
    { method: 'POST' }
  );
}

/**
 * The pending issues, kept current while a page is open.
 *
 * Issues change when a sync applies, and nothing in the app fires when a sync
 * job finishes, so the list re-checks on the Google status cadence instead of
 * waiting out the app-wide five-minute staleTime.
 */
export function useContactImportIssues(contactId?: string) {
  return useQuery({
    queryKey: contactImportIssueKeys.list(contactId),
    queryFn: () => fetchContactImportIssues(contactId),
    staleTime: 30 * 1000,
    refetchInterval: 60 * 1000,
  });
}

/** Dismiss an issue; every list holding it (contact and all) refetches. */
export function useDismissContactImportIssue() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: dismissContactImportIssue,
    onSuccess: () => {
      toast.success('Skipped address dismissed');
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
    onSettled: () =>
      invalidateAfterMutation(queryClient, {
        queryKey: contactImportIssueKeys.all,
      }),
  });
}
