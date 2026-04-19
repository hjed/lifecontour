/**
 * Integration API client functions using TanStack Query.
 *
 * Provides typed API functions for integration management operations
 * with proper error handling and caching.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import {
  GoogleStatusResponse,
  GoogleCalendarListResponse,
  SyncJobResponse,
  SyncJobListResponse,
  IntegrationHealthResponse,
  SyncType,
  SyncTriggerRequest,
  SyncHistoryFilters,
  OAuthAuthorizeRequest,
  OAuthAuthorizeResponse,
  OAuthCallbackRequest,
  OAuthCallbackResponse,
  OAuthDisconnectResponse,
  IntegrationStatsResponse,
} from '@/types/integrations';
import { JsonApiErrorResponse } from '@/types/api';

// Polling configuration constants
const INITIAL_POLL_COUNT = 3;
const INITIAL_POLL_INTERVAL = 5000; // 5 seconds
const EXTENDED_POLL_INTERVAL = 10000; // 10 seconds

// Query Keys
export const integrationKeys = {
  all: ['integrations'] as const,
  googleContacts: () => [...integrationKeys.all, 'google'] as const,
  googleContactsStatus: () =>
    [...integrationKeys.googleContacts(), 'status'] as const,
  googleCalendars: () =>
    [...integrationKeys.all, 'google', 'calendars'] as const,
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

      // Validate error structure and provide appropriate message
      let errorMessage: string;
      if (
        Array.isArray(errorData.errors) &&
        errorData.errors.length > 0 &&
        typeof errorData.errors[0].detail === 'string'
      ) {
        errorMessage = errorData.errors[0].detail;
      } else {
        errorMessage = `Request failed with status ${response.status}`;
      }

      throw new Error(errorMessage);
    } catch (parseError) {
      // If JSON parsing fails, include the parsing error in the message for better debugging
      const errorDetails =
        parseError instanceof Error ? parseError.message : String(parseError);
      throw new Error(
        `HTTP ${response.status}: ${response.statusText} (JSON parsing failed: ${errorDetails})`
      );
    }
  }
  return response.json();
}

// API Functions
export async function fetchGoogleStatus(): Promise<GoogleStatusResponse> {
  const response = await fetch('/api/integrations/google/contacts/status', {
    credentials: 'include',
  });
  return handleApiResponse<GoogleStatusResponse>(response);
}

export async function triggerGoogleSync(
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
  const url = `/api/integrations/google/contacts/sync-history${
    queryString ? `?${queryString}` : ''
  }`;

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
export function useGoogleStatus() {
  return useQuery({
    queryKey: integrationKeys.googleContactsStatus(),
    queryFn: fetchGoogleStatus,
    staleTime: 30 * 1000, // 30 seconds
    refetchInterval: 60 * 1000, // 1 minute
  });
}

export function useGoogleSync() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: triggerGoogleSync,
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

export async function triggerCalendarSync(
  syncType: SyncType = 'smart'
): Promise<SyncJobResponse> {
  const requestData: SyncTriggerRequest = { sync_type: syncType };

  const response = await fetch('/api/integrations/google/calendar/sync', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    credentials: 'include',
    body: JSON.stringify(requestData),
  });
  return handleApiResponse<SyncJobResponse>(response);
}

export function useCalendarSync() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: triggerCalendarSync,
    onSuccess: data => {
      // Invalidate status and sync history queries
      queryClient.invalidateQueries({
        queryKey: integrationKeys.googleContactsStatus(),
      });
      queryClient.invalidateQueries({ queryKey: integrationKeys.syncJobs() });

      toast.success('Calendar Sync started successfully');

      // Start polling for job status
      const jobId = data.data.id;
      queryClient.invalidateQueries({
        queryKey: integrationKeys.syncJob(jobId),
      });
    },
    onError: (error: Error) => {
      toast.error(`Failed to start calendar sync: ${error.message}`);
    },
  });
}

export function useSyncJobStatus(jobId: string | null) {
  return useQuery({
    queryKey: jobId ? integrationKeys.syncJob(jobId) : [],
    queryFn: () => (jobId ? fetchSyncJobStatus(jobId) : Promise.resolve(null)),
    enabled: !!jobId,
    refetchInterval: query => {
      // Poll with progressive intervals for better performance
      const status = query.state.data?.data?.attributes?.status;
      if (status === 'running' || status === 'queued') {
        const fetchCount = query.state.dataUpdateCount || 0;
        return fetchCount < INITIAL_POLL_COUNT
          ? INITIAL_POLL_INTERVAL
          : EXTENDED_POLL_INTERVAL;
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

// OAuth Integration Functions

/**
 * Initiate Google Contacts OAuth authorization flow.
 */
export function useGoogleOAuthAuthorize() {
  return useMutation<OAuthAuthorizeResponse, Error, OAuthAuthorizeRequest>({
    mutationFn: async (request: OAuthAuthorizeRequest) => {
      const response = await fetch(
        '/api/integrations/google/contacts/oauth/authorize',
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify(request),
          credentials: 'include',
        }
      );

      return handleApiResponse<OAuthAuthorizeResponse>(response);
    },
    onSuccess: (data: OAuthAuthorizeResponse) => {
      // Redirect to Google OAuth authorization URL
      globalThis.location.href = data.authorization_url;
    },
    onError: (error: Error) => {
      toast.error(`Failed to initiate OAuth: ${error.message}`);
    },
  });
}

/**
 * Handle Google Contacts OAuth callback.
 */
export function useGoogleOAuthCallback() {
  const queryClient = useQueryClient();

  return useMutation<OAuthCallbackResponse, Error, OAuthCallbackRequest>({
    mutationFn: async (request: OAuthCallbackRequest) => {
      const response = await fetch(
        '/api/integrations/google/contacts/oauth/callback',
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify(request),
          credentials: 'include',
        }
      );

      return handleApiResponse<OAuthCallbackResponse>(response);
    },
    onSuccess: (data: OAuthCallbackResponse) => {
      // Invalidate integration status to refresh connection state
      queryClient.invalidateQueries({
        queryKey: integrationKeys.googleContactsStatus(),
      });

      toast.success(data.message);

      // Redirect to the specified URL
      if (data.redirect_url) {
        globalThis.location.href = data.redirect_url;
      }
    },
    onError: (error: Error) => {
      toast.error(`OAuth failed: ${error.message}`);
    },
  });
}

/**
 * Disconnect Google Contacts OAuth integration.
 */
export function useGoogleOAuthDisconnect() {
  const queryClient = useQueryClient();

  return useMutation<OAuthDisconnectResponse, Error, void>({
    mutationFn: async () => {
      const response = await fetch(
        '/api/integrations/google/contacts/oauth/disconnect',
        {
          method: 'DELETE',
          credentials: 'include',
        }
      );

      return handleApiResponse<OAuthDisconnectResponse>(response);
    },
    onSuccess: (data: OAuthDisconnectResponse) => {
      // Invalidate integration status to refresh connection state
      queryClient.invalidateQueries({
        queryKey: integrationKeys.googleContactsStatus(),
      });

      toast.success(data.message);
    },
    onError: (error: Error) => {
      toast.error(`Failed to disconnect: ${error.message}`);
    },
  });
}

// Google Calendar List Functions

/**
 * Fetch the list of Google Calendars for the authenticated user.
 */
export async function fetchGoogleCalendars(): Promise<GoogleCalendarListResponse> {
  const response = await fetch('/api/integrations/google/calendars', {
    credentials: 'include',
  });
  return handleApiResponse<GoogleCalendarListResponse>(response);
}

/**
 * Hook to fetch Google Calendars. Only enabled when Google is connected.
 */
export function useGoogleCalendars(enabled: boolean = true) {
  return useQuery({
    queryKey: integrationKeys.googleCalendars(),
    queryFn: fetchGoogleCalendars,
    enabled,
    staleTime: 5 * 60 * 1000, // 5 minutes
  });
}
