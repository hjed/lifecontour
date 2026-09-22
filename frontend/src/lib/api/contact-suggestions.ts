/**
 * Contact suggestion API client functions using TanStack Query.
 *
 * Suggestions are participant emails seen on at least five of the user's
 * synced events that match no contact. Each can be accepted into a new or
 * existing contact -- which links that contact to the past events -- or
 * ignored, persistently and reversibly.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { JsonApiErrorResponse } from '@/types/api';
import {
  AcceptContactSuggestionRequest,
  AcceptContactSuggestionTarget,
  ContactSuggestionAcceptanceResponse,
  ContactSuggestionListResponse,
  IgnoreContactSuggestionRequest,
  IgnoredContactSuggestionListResponse,
} from '@/types/contact-suggestions';
import { contactKeys } from './contacts';
import { invalidateAfterMutation } from './invalidate-after-mutation';
import { journalKeys } from './journal-keys';

const BASE_URL = '/api/integrations/contact-suggestions';

export const contactSuggestionKeys = {
  all: ['contact-suggestions'] as const,
  list: () => [...contactSuggestionKeys.all, 'list'] as const,
  ignored: () => [...contactSuggestionKeys.all, 'ignored'] as const,
};

async function request<T>(
  url: string,
  failureMessage: string,
  init: RequestInit = {}
): Promise<T> {
  const response = await fetch(url, {
    credentials: 'include',
    ...init,
    headers: init.body
      ? { 'Content-Type': 'application/json', ...init.headers }
      : init.headers,
  });
  if (!response.ok) {
    const errorData: Partial<JsonApiErrorResponse> = await response
      .json()
      .catch(() => ({}));
    throw new Error(errorData.errors?.[0]?.detail || failureMessage);
  }
  return (response.status === 204 ? undefined : await response.json()) as T;
}

export function fetchContactSuggestions(): Promise<ContactSuggestionListResponse> {
  return request(BASE_URL, 'Failed to load contact suggestions');
}

export function fetchIgnoredContactSuggestions(): Promise<IgnoredContactSuggestionListResponse> {
  return request(`${BASE_URL}/ignored`, 'Failed to load ignored suggestions');
}

export interface AcceptContactSuggestionVariables {
  email: string;
  target: AcceptContactSuggestionTarget;
}

export function acceptContactSuggestion({
  email,
  target,
}: AcceptContactSuggestionVariables): Promise<ContactSuggestionAcceptanceResponse> {
  const body: AcceptContactSuggestionRequest = {
    data: {
      type: 'contact-suggestion-acceptances',
      attributes: { email, target },
    },
  };
  return request(`${BASE_URL}/accept`, 'Failed to accept suggestion', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export function ignoreContactSuggestion(email: string): Promise<unknown> {
  const body: IgnoreContactSuggestionRequest = {
    data: { type: 'ignored-contact-suggestions', attributes: { email } },
  };
  return request(`${BASE_URL}/ignored`, 'Failed to ignore suggestion', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export function unignoreContactSuggestion(email: string): Promise<void> {
  return request(
    `${BASE_URL}/ignored/${encodeURIComponent(email)}`,
    'Failed to restore suggestion',
    { method: 'DELETE' }
  );
}

// Hooks

export function useContactSuggestions() {
  return useQuery({
    queryKey: contactSuggestionKeys.list(),
    queryFn: fetchContactSuggestions,
  });
}

export function useIgnoredContactSuggestions() {
  return useQuery({
    queryKey: contactSuggestionKeys.ignored(),
    queryFn: fetchIgnoredContactSuggestions,
  });
}

/**
 * Accept a suggestion. The contact list and journals change too: a contact is
 * created or gains an email, and past journals gain it as a participant.
 */
export function useAcceptContactSuggestion() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: acceptContactSuggestion,
    onSuccess: response => {
      const { email, linked_journal_count } = response.data.attributes;
      toast.success(
        `${email} saved to contact and linked to ${linked_journal_count} event${
          linked_journal_count === 1 ? '' : 's'
        }`
      );
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
    onSettled: () =>
      invalidateAfterMutation(
        queryClient,
        { queryKey: contactSuggestionKeys.all },
        { queryKey: contactKeys.all },
        { queryKey: journalKeys.all }
      ),
  });
}

export function useIgnoreContactSuggestion() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ignoreContactSuggestion,
    onSuccess: (_data, email) => {
      toast.success(`${email} will no longer be suggested`);
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
    onSettled: () =>
      invalidateAfterMutation(queryClient, {
        queryKey: contactSuggestionKeys.all,
      }),
  });
}

export function useUnignoreContactSuggestion() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: unignoreContactSuggestion,
    onError: (error: Error) => {
      toast.error(error.message);
    },
    onSettled: () =>
      invalidateAfterMutation(queryClient, {
        queryKey: contactSuggestionKeys.all,
      }),
  });
}
