import { useQuery } from '@tanstack/react-query';
import { JsonApiErrorResponse } from '@/types/api';
import { GlobalSearchResponse, GlobalSearchFilters } from '@/types/search';
import { API_ENDPOINTS, ERROR_MESSAGES } from '@/lib/constants';

export const searchKeys = {
  all: ['search'] as const,
  global: (filters: GlobalSearchFilters) =>
    [...searchKeys.all, 'global', filters] as const,
};

export async function searchGlobal(
  filters: GlobalSearchFilters
): Promise<GlobalSearchResponse> {
  const params = new URLSearchParams();

  if (filters.q) params.append('q', filters.q);
  if (filters.page !== undefined)
    params.append('page', filters.page.toString());
  if (filters.limit !== undefined)
    params.append('limit', filters.limit.toString());
  if (filters.entity_types?.length) {
    filters.entity_types.forEach(type => params.append('entity_types', type));
  }

  const url = `${API_ENDPOINTS.SEARCH.GLOBAL}?${params.toString()}`;

  const response = await fetch(url, {
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
    },
  });

  if (!response.ok) {
    const errorData: JsonApiErrorResponse = await response.json();
    throw new Error(
      errorData.errors?.[0]?.detail || ERROR_MESSAGES.SEARCH_FAILED
    );
  }

  return response.json();
}

export function useGlobalSearch(
  filters: GlobalSearchFilters,
  options: { enabled?: boolean } = {}
) {
  return useQuery({
    queryKey: searchKeys.global(filters),
    queryFn: () => searchGlobal(filters),
    enabled: options.enabled ?? filters.q?.trim().length > 0,
    staleTime: 2 * 60 * 1000, // 2 minutes
  });
}
