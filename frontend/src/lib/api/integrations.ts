/**
 * Integration API client functions using TanStack Query.
 *
 * Provides typed API functions for integration management operations
 * with proper error handling and caching.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import {
  GoogleContactsStatusResponse,
  SyncJobResponse,
  SyncJobListResponse,
  IntegrationHealthResponse,
  SyncType,
  SyncTriggerRequest,
  SyncHistoryFilters,
  OAuthConnectionRequest,
  OAuthConnectionResponse,
  IntegrationStatsResponse,
} from '@/types/integrations';
import { JsonApiErrorResponse } from '@/types/api';

// Query Keys
export const integrationKeys = {
  all: ['integrations'] as const,
  googleContacts: () => [...integrationKeys.all, 'google-contacts'] as const,
  googleContactsStatus: () =>
    [...integrationKeys.googleContacts(), 'status'] as const,
  syncJobs: () => [...integrationKeys.all, 'sync-jobs'] as const,
  syncJob: (jobId: string) => [...integrationKeys.syncJobs(), jobId] as const,
  syncHistory: (filters: SyncHistoryFilters) =>
    [...integrationKeys.syncJobs(), 'history', filters] as const,
  health: () => [...integrationKeys.all, 'health'] as const,
  stats: () => [...integrationKeys.all, 'stats'] as const,
};

// Error handling helper
async function handleApiResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    try {
      const errorData: JsonApiErrorResponse = await response.json();
      const errorMessage =
        errorData.errors?.[0]?.detail ||
        `Request failed with status ${response.status}`;
      throw new Error(errorMessage);
    } catch {
      // If JSON parsing fails, use status text
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }
  }
  return response.json();
}

// API Functions
export async function fetchGoogleContactsStatus(): Promise<GoogleContactsStatusResponse> {
  const response = await fetch('/api/integrations/google/contacts/status', {
    credentials: 'include',
  });
  return handleApiResponse<GoogleContactsStatusResponse>(response);
}

export async function triggerGoogleContactsSync(
  syncType: SyncType = 'smart'
): Promise<SyncJobResponse> {
  const requestData: SyncTriggerRequest = { sync_type: syncType };

  const response = await fetch('/api/integrations/google/contacts/sync', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    credentials: 'include',
    body: JSON.stringify(requestData),
  });
  return handleApiResponse<SyncJobResponse>(response);
}

export async function fetchSyncJobStatus(
  jobId: string
): Promise<SyncJobResponse> {
  const response = await fetch(
    `/api/integrations/google/contacts/sync/${jobId}`,
    {
      credentials: 'include',
    }
  );
  return handleApiResponse<SyncJobResponse>(response);
}

export async function fetchSyncHistory(
  filters: SyncHistoryFilters = {}
): Promise<SyncJobListResponse> {
  const params = new URLSearchParams();

  if (filters.status) params.append('status', filters.status);
  if (filters.syncType) params.append('sync_type', filters.syncType);
  if (filters.dateFrom) params.append('date_from', filters.dateFrom);
  if (filters.dateTo) params.append('date_to', filters.dateTo);
  if (filters.limit) params.append('limit', filters.limit.toString());
  if (filters.offset) params.append('offset', filters.offset.toString());

  const queryString = params.toString();
  const url = `/api/integrations/google/contacts/sync${queryString ? `?${queryString}` : ''}`;

  const response = await fetch(url, {
    credentials: 'include',
  });
  return handleApiResponse<SyncJobListResponse>(response);
}

export async function fetchIntegrationHealth(): Promise<IntegrationHealthResponse> {
  const response = await fetch('/api/integrations/health', {
    credentials: 'include',
  });
  return handleApiResponse<IntegrationHealthResponse>(response);
}

export async function fetchIntegrationStats(): Promise<IntegrationStatsResponse> {
  const response = await fetch('/api/integrations/google/contacts/stats', {
    credentials: 'include',
  });
  return handleApiResponse<IntegrationStatsResponse>(response);
}

export async function initiateOAuthConnection(
  request: OAuthConnectionRequest
): Promise<OAuthConnectionResponse> {
  const response = await fetch('/api/integrations/oauth/connect', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    credentials: 'include',
    body: JSON.stringify(request),
  });
  return handleApiResponse<OAuthConnectionResponse>(response);
}

export async function disconnectGoogleContacts(): Promise<void> {
  const response = await fetch('/api/integrations/google/contacts/disconnect', {
    method: 'POST',
    credentials: 'include',
  });

  if (!response.ok) {
    try {
      const errorData: JsonApiErrorResponse = await response.json();
      const errorMessage =
        errorData.errors?.[0]?.detail || 'Failed to disconnect';
      throw new Error(errorMessage);
    } catch {
      throw new Error(`HTTP ${response.status}: Failed to disconnect`);
    }
  }
}

export async function cancelSyncJob(jobId: string): Promise<void> {
  const response = await fetch(
    `/api/integrations/google/contacts/sync/${jobId}/cancel`,
    {
      method: 'POST',
      credentials: 'include',
    }
  );

  if (!response.ok) {
    try {
      const errorData: JsonApiErrorResponse = await response.json();
      const errorMessage =
        errorData.errors?.[0]?.detail || 'Failed to cancel sync job';
      throw new Error(errorMessage);
    } catch {
      throw new Error(`HTTP ${response.status}: Failed to cancel sync job`);
    }
  }
}

// React Query Hooks
export function useGoogleContactsStatus() {
  return useQuery({
    queryKey: integrationKeys.googleContactsStatus(),
    queryFn: fetchGoogleContactsStatus,
    staleTime: 30 * 1000, // 30 seconds
    refetchInterval: 60 * 1000, // 1 minute
  });
}

export function useGoogleContactsSync() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: triggerGoogleContactsSync,
    onSuccess: data => {
      // Invalidate status and sync history queries
      queryClient.invalidateQueries({
        queryKey: integrationKeys.googleContactsStatus(),
      });
      queryClient.invalidateQueries({ queryKey: integrationKeys.syncJobs() });

      toast.success('Sync started successfully');

      // Start polling for job status
      const jobId = data.data.id;
      queryClient.invalidateQueries({
        queryKey: integrationKeys.syncJob(jobId),
      });
    },
    onError: (error: Error) => {
      toast.error(`Failed to start sync: ${error.message}`);
    },
  });
}

export function useSyncJobStatus(jobId: string | null) {
  return useQuery({
    queryKey: jobId ? integrationKeys.syncJob(jobId) : [],
    queryFn: () => (jobId ? fetchSyncJobStatus(jobId) : Promise.resolve(null)),
    enabled: !!jobId,
    refetchInterval: query => {
      // Poll with progressive intervals: 5s initially, then 10s for better performance
      const status = query.state.data?.data?.attributes?.status;
      if (status === 'running' || status === 'queued') {
        const fetchCount = query.state.dataUpdateCount || 0;
        return fetchCount < 3 ? 5000 : 10000; // 5s for first 3 polls, then 10s
      }
      return false;
    },
    staleTime: 1000, // 1 second
  });
}

export function useSyncHistory(filters: SyncHistoryFilters = {}) {
  return useQuery({
    queryKey: integrationKeys.syncHistory(filters),
    queryFn: () => fetchSyncHistory(filters),
    staleTime: 30 * 1000, // 30 seconds
  });
}

export function useIntegrationHealth() {
  return useQuery({
    queryKey: integrationKeys.health(),
    queryFn: fetchIntegrationHealth,
    staleTime: 10 * 1000, // 10 seconds
    refetchInterval: 30 * 1000, // 30 seconds
  });
}

export function useIntegrationStats() {
  return useQuery({
    queryKey: integrationKeys.stats(),
    queryFn: fetchIntegrationStats,
    staleTime: 5 * 60 * 1000, // 5 minutes
  });
}

/**
 * Hook to initiate OAuth connection.
 * @param redirect Optional function to handle redirect (e.g., for testing or SSR).
 */
export function useOAuthConnection(redirect?: (url: string) => void) {
  return useMutation({
    mutationFn: initiateOAuthConnection,
    onSuccess: data => {
      // Redirect to OAuth URL using provided function or default to window.location.href
      const url = data.data.attributes.authUrl;
      if (redirect) {
        redirect(url);
      } else if (typeof window !== 'undefined') {
        window.location.href = url;
      }
    },
    onError: (error: Error) => {
      toast.error(`Failed to initiate OAuth: ${error.message}`);
    },
  });
}

export function useDisconnectGoogleContacts() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: disconnectGoogleContacts,
    onSuccess: () => {
      // Invalidate all integration queries
      queryClient.invalidateQueries({ queryKey: integrationKeys.all });
      toast.success('Google Contacts disconnected successfully');
    },
    onError: (error: Error) => {
      toast.error(`Failed to disconnect: ${error.message}`);
    },
  });
}

export function useCancelSyncJob() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: cancelSyncJob,
    onSuccess: (_, jobId) => {
      // Invalidate job status and sync history
      queryClient.invalidateQueries({
        queryKey: integrationKeys.syncJob(jobId),
      });
      queryClient.invalidateQueries({ queryKey: integrationKeys.syncJobs() });
      toast.success('Sync job cancelled');
    },
    onError: (error: Error) => {
      toast.error(`Failed to cancel sync: ${error.message}`);
    },
  });
}
