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
import {
  API_ENDPOINTS,
  ERROR_MESSAGES,
  SUCCESS_MESSAGES,
} from '@/lib/constants';

// Query Keys
export const routeKeys = {
  all: ['routes'] as const,
  lists: () => [...routeKeys.all, 'list'] as const,
  list: (filters: RouteFilters) => [...routeKeys.lists(), filters] as const,
  details: () => [...routeKeys.all, 'detail'] as const,
  detail: (id: string) => [...routeKeys.details(), id] as const,
};

// API Functions
async function fetchRoutes(
  filters: RouteFilters = {}
): Promise<RouteListResponse> {
  const params = new URLSearchParams();

  if (filters.name) params.append('name', filters.name);
  if (filters.page) params.append('page', filters.page.toString());
  if (filters.limit) params.append('limit', filters.limit.toString());

  const url = params.toString()
    ? `${API_ENDPOINTS.ROUTES.BASE}?${params.toString()}`
    : API_ENDPOINTS.ROUTES.BASE;

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

async function fetchRoute(id: string): Promise<RouteResponse> {
  const response = await fetch(API_ENDPOINTS.ROUTES.BY_ID(id), {
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

async function createRoute(data: RouteFormData): Promise<RouteResponse> {
  const requestData = {
    type: 'routes' as const,
    attributes: data,
  };

  const response = await fetch(API_ENDPOINTS.ROUTES.BASE, {
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
  filters: RouteFilters = {},
  options: { enabled?: boolean } = {}
) {
  return useQuery({
    queryKey: routeKeys.list(filters),
    queryFn: () => fetchRoutes(filters),
    staleTime: 5 * 60 * 1000, // 5 minutes
    enabled: options.enabled,
  });
}

export function useRoute(id: string) {
  return useQuery({
    queryKey: routeKeys.detail(id),
    queryFn: () => fetchRoute(id),
    enabled: !!id,
    staleTime: 5 * 60 * 1000, // 5 minutes
  });
}

export function useCreateRoute() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: createRoute,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: routeKeys.all });
      toast.success(SUCCESS_MESSAGES.CREATE_SUCCESS);
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });
}
