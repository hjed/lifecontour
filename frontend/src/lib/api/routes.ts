/**
 * Route API client functions using TanStack Query.
 *
 * Provides typed API functions for route management operations
 * with proper error handling and caching.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import {
  RouteListResponse,
  RouteResponse,
  RouteFormData,
  RouteFilters,
} from '@/types/routes';
import { JsonApiErrorResponse } from '@/types/api';
import { ERROR_MESSAGES, SUCCESS_MESSAGES } from '@/lib/constants';

// Query Keys
export const routeKeys = {
  all: (journalId: string) => ['journals', journalId, 'routes'] as const,
  lists: (journalId: string) => [...routeKeys.all(journalId), 'list'] as const,
  list: (journalId: string, filters: RouteFilters) =>
    [...routeKeys.lists(journalId), filters] as const,
  details: (journalId: string) =>
    [...routeKeys.all(journalId), 'detail'] as const,
  detail: (journalId: string, id: string) =>
    [...routeKeys.details(journalId), id] as const,
};

// API Functions
async function fetchRoutes(
  journalId: string,
  filters: RouteFilters = {}
): Promise<RouteListResponse> {
  const params = new URLSearchParams();

  if (filters.name) params.append('name', filters.name);
  if (filters.page) params.append('page', filters.page.toString());
  if (filters.limit) params.append('limit', filters.limit.toString());

  const encJournalId = encodeURIComponent(journalId);
  const baseUrl = `/api/journals/${encJournalId}/routes`;
  const url = params.toString() ? `${baseUrl}?${params.toString()}` : baseUrl;

  const response = await fetch(url, {
    credentials: 'include',
  });

  if (!response.ok) {
    const errorData: JsonApiErrorResponse = await response.json();
    throw new Error(
      errorData.errors?.[0]?.detail || ERROR_MESSAGES.FETCH_FAILED
    );
  }

  return response.json();
}

async function fetchRoute(
  journalId: string,
  routeId: string
): Promise<RouteResponse> {
  const encJournalId = encodeURIComponent(journalId);
  const encRouteId = encodeURIComponent(routeId);
  const response = await fetch(
    `/api/journals/${encJournalId}/routes/${encRouteId}`,
    {
      credentials: 'include',
    }
  );

  if (!response.ok) {
    const errorData: JsonApiErrorResponse = await response.json();
    throw new Error(
      errorData.errors?.[0]?.detail || ERROR_MESSAGES.FETCH_FAILED
    );
  }

  return response.json();
}

async function createRoute(
  journalId: string,
  data: RouteFormData
): Promise<RouteResponse> {
  const requestData = {
    type: 'routes' as const,
    attributes: data,
  };

  const encJournalId = encodeURIComponent(journalId);
  const response = await fetch(`/api/journals/${encJournalId}/routes`, {
    method: 'POST',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ data: requestData }),
  });

  if (!response.ok) {
    const errorData: JsonApiErrorResponse = await response.json();
    throw new Error(
      errorData.errors?.[0]?.detail || ERROR_MESSAGES.CREATE_FAILED
    );
  }

  return response.json();
}

// React Query Hooks
export function useRoutes(
  journalId: string,
  filters: RouteFilters = {},
  options: { enabled?: boolean } = {}
) {
  return useQuery({
    queryKey: routeKeys.list(journalId, filters),
    queryFn: () => fetchRoutes(journalId, filters),
    staleTime: 5 * 60 * 1000, // 5 minutes
    enabled: !!journalId && (options.enabled ?? true),
  });
}

export function useRoute(journalId: string, routeId: string) {
  return useQuery({
    queryKey: routeKeys.detail(journalId, routeId),
    queryFn: () => fetchRoute(journalId, routeId),
    enabled: !!journalId && !!routeId,
    staleTime: 5 * 60 * 1000, // 5 minutes
  });
}

export function useCreateRoute() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      journalId,
      data,
    }: {
      journalId: string;
      data: RouteFormData;
      silent?: boolean;
    }) => createRoute(journalId, data),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({
        queryKey: routeKeys.all(variables.journalId),
      });
      if (!variables.silent) {
        toast.success(SUCCESS_MESSAGES.CREATE_SUCCESS);
      }
    },
    onError: (error: Error, variables) => {
      if (!variables.silent) {
        toast.error(error.message);
      }
    },
  });
}
