/**
 * Incomplete outdoor activities API client functions using TanStack Query.
 *
 * The incomplete review is an advisory projection over the user's outdoor
 * journals (see the Outdoor Logbook Improvements spec): each entry names the
 * rule(s) it matches and can be dismissed (reversibly) from the review.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { EventDateRange, JournalType } from '@/types/journals';
import { JsonApiErrorResponse } from '@/types/api';
import { API_ENDPOINTS, ERROR_MESSAGES } from '@/lib/constants';

// Reason enum values as serialized by the backend IncompletenessReason enum
export type IncompletenessReason =
  'no_attributes' | 'missing_template' | 'no_participants';

export interface IncompleteOutdoorActivityAttributes {
  title: string;
  event_date_range: EventDateRange;
  subtypes: JournalType[];
  reasons: IncompletenessReason[];
  dismissed: boolean;
}

export interface IncompleteOutdoorActivityResource {
  type: string;
  id: string;
  attributes: IncompleteOutdoorActivityAttributes;
  links?: { self?: string };
}

export interface IncompleteOutdoorActivitiesListResponse {
  data: IncompleteOutdoorActivityResource[];
}

// Query Keys
export const incompleteOutdoorActivityKeys = {
  all: ['incomplete-outdoor-activities'] as const,
  lists: () => [...incompleteOutdoorActivityKeys.all, 'list'] as const,
  list: (includeDismissed: boolean) =>
    [...incompleteOutdoorActivityKeys.lists(), { includeDismissed }] as const,
};

// API Functions
async function fetchIncompleteOutdoorActivities(
  includeDismissed: boolean
): Promise<IncompleteOutdoorActivitiesListResponse> {
  const url = includeDismissed
    ? `${API_ENDPOINTS.JOURNALS.INCOMPLETE_OUTDOOR_ACTIVITIES}?include_dismissed=true`
    : API_ENDPOINTS.JOURNALS.INCOMPLETE_OUTDOOR_ACTIVITIES;

  const response = await fetch(url, {
    credentials: 'include',
  });

  if (!response.ok) {
    const errorData: JsonApiErrorResponse = await response
      .json()
      .catch(() => ({}));
    throw new Error(
      errorData.errors?.[0]?.detail || ERROR_MESSAGES.FETCH_FAILED
    );
  }

  return response.json();
}

async function postDismissalAction(
  url: string,
  failureMessage: string
): Promise<unknown> {
  const response = await fetch(url, {
    method: 'POST',
    credentials: 'include',
  });

  if (!response.ok) {
    const errorData: JsonApiErrorResponse = await response
      .json()
      .catch(() => ({}));
    throw new Error(errorData.errors?.[0]?.detail || failureMessage);
  }

  return response.json();
}

async function dismissIncompleteOutdoorActivity(
  journalId: string
): Promise<unknown> {
  return postDismissalAction(
    API_ENDPOINTS.JOURNALS.INCOMPLETE_OUTDOOR_ACTIVITY_DISMISS(journalId),
    'Failed to dismiss activity'
  );
}

async function undismissIncompleteOutdoorActivity(
  journalId: string
): Promise<unknown> {
  return postDismissalAction(
    API_ENDPOINTS.JOURNALS.INCOMPLETE_OUTDOOR_ACTIVITY_UNDISMISS(journalId),
    'Failed to restore activity'
  );
}

// Hooks

/**
 * The user's incomplete outdoor activities, newest first. With
 * `includeDismissed`, dismissed entries are returned flagged
 * `dismissed: true` so the UI can offer un-dismiss.
 */
export function useIncompleteOutdoorActivities(includeDismissed = false) {
  return useQuery({
    queryKey: incompleteOutdoorActivityKeys.list(includeDismissed),
    queryFn: () => fetchIncompleteOutdoorActivities(includeDismissed),
  });
}

/**
 * Dismiss an activity from the incomplete review. Optimistically removes the
 * entry from the default (non-dismissed) list; the success toast offers Undo.
 */
export function useDismissIncompleteOutdoorActivity() {
  const queryClient = useQueryClient();

  const invalidateLists = () =>
    queryClient.invalidateQueries({
      queryKey: incompleteOutdoorActivityKeys.lists(),
    });

  return useMutation({
    mutationFn: dismissIncompleteOutdoorActivity,
    // Optimistically drop the entry from the default list so the review
    // updates immediately; the include-dismissed variant refetches instead
    // (there the row flips to its dismissed state rather than disappearing).
    onMutate: async (journalId: string) => {
      await queryClient.cancelQueries({
        queryKey: incompleteOutdoorActivityKeys.lists(),
      });
      const defaultListKey = incompleteOutdoorActivityKeys.list(false);
      const previousList =
        queryClient.getQueryData<IncompleteOutdoorActivitiesListResponse>(
          defaultListKey
        );
      queryClient.setQueryData<IncompleteOutdoorActivitiesListResponse>(
        defaultListKey,
        old =>
          old
            ? { ...old, data: old.data.filter(entry => entry.id !== journalId) }
            : old
      );
      return { previousList };
    },
    onError: (error: Error, _journalId, context) => {
      if (context?.previousList) {
        queryClient.setQueryData(
          incompleteOutdoorActivityKeys.list(false),
          context.previousList
        );
      }
      toast.error(error.message);
    },
    onSuccess: (_data, journalId) => {
      toast.success('Activity dismissed from the incomplete review', {
        action: {
          label: 'Undo',
          onClick: () => {
            undismissIncompleteOutdoorActivity(journalId)
              .then(invalidateLists)
              .catch((error: Error) => toast.error(error.message));
          },
        },
      });
    },
    onSettled: invalidateLists,
  });
}

/**
 * Restore a dismissed activity to the incomplete review.
 */
export function useUndismissIncompleteOutdoorActivity() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: undismissIncompleteOutdoorActivity,
    onError: (error: Error) => {
      toast.error(error.message);
    },
    onSuccess: () => {
      toast.success('Activity restored to the incomplete review');
    },
    onSettled: () => {
      queryClient.invalidateQueries({
        queryKey: incompleteOutdoorActivityKeys.lists(),
      });
    },
  });
}
