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
  IntegrationListResponse,
  DeadLetterListResponse,
  StravaAthleteMappingListResponse,
  StravaAthleteMappingResponse,
  StravaAthleteMappingCreateRequest,
  UnmatchedStravaAthleteListResponse,
  WebhookReregisterResponse,
  WebhookUrlResponse,
  ImmichConflictListResponse,
  ImmichConflictResponse,
} from '@/types/integrations';
import { JsonApiErrorResponse } from '@/types/api';
import { invalidateAfterMutation } from './invalidate-after-mutation';

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
  syncHistory: (integrationId: string, filters: SyncHistoryFilters) =>
    [...integrationKeys.syncJobs(), integrationId, 'history', filters] as const,
  health: () => [...integrationKeys.all, 'health'] as const,
  stats: () => [...integrationKeys.all, 'stats'] as const,
  list: () => [...integrationKeys.all, 'list'] as const,
  deadLetters: (limit: number, offset: number) =>
    [...integrationKeys.all, 'dead-letters', limit, offset] as const,
  stravaMappings: () => [...integrationKeys.all, 'strava', 'mappings'] as const,
  stravaJournalUnmatched: (journalId: string) =>
    [...integrationKeys.all, 'strava', 'unmatched', journalId] as const,
  immichConflicts: () =>
    [...integrationKeys.all, 'immich', 'conflicts'] as const,
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

export async function fetchIntegrations(): Promise<IntegrationListResponse> {
  const response = await fetch('/api/integrations', {
    credentials: 'include',
  });
  return handleApiResponse<IntegrationListResponse>(response);
}

export async function fetchDeadLetters(
  limit: number = 50,
  offset: number = 0
): Promise<DeadLetterListResponse> {
  const params = new URLSearchParams();
  params.append('limit', limit.toString());
  params.append('offset', offset.toString());

  const response = await fetch(
    `/api/health/dead-letters?${params.toString()}`,
    {
      credentials: 'include',
    }
  );
  return handleApiResponse<DeadLetterListResponse>(response);
}

export async function triggerSync(
  integrationId: string,
  capability: string,
  syncType: SyncType = 'smart'
): Promise<SyncJobResponse> {
  const requestData: SyncTriggerRequest = { sync_type: syncType };

  const response = await fetch(
    `/api/integrations/${integrationId}/${capability.replace('_sync', '')}/sync`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      credentials: 'include',
      body: JSON.stringify(requestData),
    }
  );
  return handleApiResponse<SyncJobResponse>(response);
}

export function useGenericSync(integrationId: string, capability: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (syncType: SyncType = 'smart') =>
      triggerSync(integrationId, capability, syncType),
    onSuccess: data => {
      // Invalidate status and sync history queries
      void invalidateAfterMutation(
        queryClient,
        { queryKey: integrationKeys.list() },
        { queryKey: integrationKeys.syncJobs() }
      );

      // Legacy fallback
      if (integrationId === 'google') {
        void invalidateAfterMutation(queryClient, {
          queryKey: integrationKeys.googleContactsStatus(),
        });
      }

      toast.success(`${capability} Sync started successfully`);

      // Start polling for job status
      const jobId = data.data.id;
      void invalidateAfterMutation(queryClient, {
        queryKey: integrationKeys.syncJob(jobId),
      });
    },
    onError: (error: Error) => {
      toast.error(`Failed to start ${capability} sync: ${error.message}`);
    },
  });
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
  integrationId: string,
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
  const url = `/api/integrations/${integrationId}/sync-history${
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

export interface ConsumerGroupLag {
  name: string;
  consumers: number;
  pending: number;
  lag?: number;
  'last-delivered-id'?: string;
  'entries-read'?: number;
}

export async function fetchConsumerLag(): Promise<ConsumerGroupLag[]> {
  const response = await fetch('/api/health/consumer-lag', {
    credentials: 'include',
  });
  return handleApiResponse<ConsumerGroupLag[]>(response);
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

export function useIntegrations() {
  return useQuery({
    queryKey: integrationKeys.list(),
    queryFn: fetchIntegrations,
    staleTime: 30 * 1000, // 30 seconds
    refetchInterval: 60 * 1000, // 1 minute
  });
}

export function useDeadLetters(limit: number = 50, offset: number = 0) {
  return useQuery({
    queryKey: integrationKeys.deadLetters(limit, offset),
    queryFn: () => fetchDeadLetters(limit, offset),
    staleTime: 30 * 1000, // 30 seconds
  });
}

export function useGoogleSync() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: triggerGoogleSync,
    onSuccess: data => {
      // Invalidate status and sync history queries
      void invalidateAfterMutation(
        queryClient,
        { queryKey: integrationKeys.googleContactsStatus() },
        { queryKey: integrationKeys.syncJobs() }
      );

      toast.success('Sync started successfully');

      // Start polling for job status
      const jobId = data.data.id;
      void invalidateAfterMutation(queryClient, {
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
      void invalidateAfterMutation(
        queryClient,
        { queryKey: integrationKeys.googleContactsStatus() },
        { queryKey: integrationKeys.syncJobs() }
      );

      toast.success('Calendar Sync started successfully');

      // Start polling for job status
      const jobId = data.data.id;
      void invalidateAfterMutation(queryClient, {
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
      // 'in_progress' is the non-blocking fan-out's active parent state — keep
      // polling it like 'running'/'queued' until the reconciler finalises it.
      if (
        status === 'running' ||
        status === 'queued' ||
        status === 'in_progress'
      ) {
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

export function useSyncHistory(
  integrationId: string,
  filters: SyncHistoryFilters = {},
  enabled: boolean = true
) {
  return useQuery({
    queryKey: integrationKeys.syncHistory(integrationId, filters),
    queryFn: () => fetchSyncHistory(integrationId, filters),
    enabled,
    staleTime: 30 * 1000, // 30 seconds
  });
}

export function useIntegrationHealth(options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: integrationKeys.health(),
    queryFn: fetchIntegrationHealth,
    staleTime: 10 * 1000, // 10 seconds
    refetchInterval: 30 * 1000, // 30 seconds
    enabled: options?.enabled,
  });
}

export function useIntegrationStats() {
  return useQuery({
    queryKey: integrationKeys.stats(),
    queryFn: fetchIntegrationStats,
    staleTime: 5 * 60 * 1000, // 5 minutes
  });
}

export function useConsumerLag(options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: [...integrationKeys.health(), 'consumer-lag'],
    queryFn: fetchConsumerLag,
    staleTime: 10 * 1000, // 10 seconds
    refetchInterval: 30 * 1000, // 30 seconds
    enabled: options?.enabled,
  });
}

export function useCancelSyncJob() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: cancelSyncJob,
    onSuccess: (_, jobId) => {
      // Invalidate job status and sync history
      void invalidateAfterMutation(
        queryClient,
        { queryKey: integrationKeys.syncJob(jobId) },
        { queryKey: integrationKeys.syncJobs() }
      );
      toast.success('Sync job cancelled');
    },
    onError: (error: Error) => {
      toast.error(`Failed to cancel sync: ${error.message}`);
    },
  });
}

// OAuth Integration Functions

/**
 * Initiate OAuth authorization flow for an integration.
 */
export function useOAuthAuthorize(integrationId: string) {
  return useMutation<OAuthAuthorizeResponse, Error, OAuthAuthorizeRequest>({
    mutationFn: async (request: OAuthAuthorizeRequest) => {
      // Map integration IDs to their specific oauth endpoints
      // In the future this might be standard, e.g., `/api/integrations/${integrationId}/oauth/authorize`
      const endpoint =
        integrationId === 'google'
          ? '/api/integrations/google/contacts/oauth/authorize'
          : `/api/integrations/${integrationId}/oauth/authorize`;

      const response = await fetch(endpoint, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(request),
        credentials: 'include',
      });

      return handleApiResponse<OAuthAuthorizeResponse>(response);
    },
    onSuccess: (data: OAuthAuthorizeResponse) => {
      // Redirect to OAuth authorization URL
      globalThis.location.href = data.authorization_url;
    },
    onError: (error: Error) => {
      toast.error(`Failed to initiate OAuth: ${error.message}`);
    },
  });
}

/**
 * Initiate Google Contacts OAuth authorization flow. (DEPRECATED: use useOAuthAuthorize instead)
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
      void invalidateAfterMutation(queryClient, {
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
 * Disconnect OAuth integration.
 */
export function useOAuthDisconnect(integrationId: string) {
  const queryClient = useQueryClient();

  return useMutation<OAuthDisconnectResponse, Error, void>({
    mutationFn: async () => {
      const endpoint =
        integrationId === 'google'
          ? '/api/integrations/google/contacts/oauth/disconnect'
          : `/api/integrations/${integrationId}/oauth/disconnect`;

      const response = await fetch(endpoint, {
        method: 'DELETE',
        credentials: 'include',
      });

      return handleApiResponse<OAuthDisconnectResponse>(response);
    },
    onSuccess: (data: OAuthDisconnectResponse) => {
      // Invalidate integration list to refresh connection state
      void invalidateAfterMutation(queryClient, {
        queryKey: integrationKeys.list(),
      });
      // Legacy cache invalidation
      if (integrationId === 'google') {
        void invalidateAfterMutation(queryClient, {
          queryKey: integrationKeys.googleContactsStatus(),
        });
      }

      toast.success(data.message);
    },
    onError: (error: Error) => {
      toast.error(`Failed to disconnect: ${error.message}`);
    },
  });
}

/**
 * Disconnect Google Contacts OAuth integration. (DEPRECATED)
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
      void invalidateAfterMutation(queryClient, {
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

// Strava Athlete Mappings

export async function fetchStravaMappings(): Promise<StravaAthleteMappingListResponse> {
  const response = await fetch('/api/integrations/strava/athlete-mappings', {
    credentials: 'include',
  });
  return handleApiResponse<StravaAthleteMappingListResponse>(response);
}

export function useStravaMappings() {
  return useQuery({
    queryKey: integrationKeys.stravaMappings(),
    queryFn: fetchStravaMappings,
    staleTime: 5 * 60 * 1000,
  });
}

export async function createStravaMapping(
  request: StravaAthleteMappingCreateRequest
): Promise<StravaAthleteMappingResponse> {
  const response = await fetch('/api/integrations/strava/athlete-mappings', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    credentials: 'include',
    body: JSON.stringify(request),
  });
  return handleApiResponse<StravaAthleteMappingResponse>(response);
}

export function useCreateStravaMapping() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: createStravaMapping,
    onSuccess: () => {
      void invalidateAfterMutation(queryClient, {
        queryKey: integrationKeys.stravaMappings(),
      });
      toast.success('Participant mapped successfully');
    },
    onError: (error: Error) => {
      toast.error(`Failed to map participant: ${error.message}`);
    },
  });
}

export async function deleteStravaMapping(
  stravaAthleteId: string
): Promise<void> {
  const response = await fetch(
    `/api/integrations/strava/athlete-mappings/${stravaAthleteId}`,
    {
      method: 'DELETE',
      credentials: 'include',
    }
  );
  if (!response.ok) {
    try {
      const errorData = await response.json();
      throw new Error(
        errorData.errors?.[0]?.detail || 'Failed to delete mapping'
      );
    } catch {
      throw new Error(`HTTP ${response.status}: Failed to delete mapping`);
    }
  }
}

export function useDeleteStravaMapping() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: deleteStravaMapping,
    // Optimistically remove the row so the table updates immediately. The
    // backend commits the delete at request teardown, so the refetch can still
    // return the mapping (read-after-write) and leave the row on screen.
    onMutate: async (stravaAthleteId: string) => {
      await queryClient.cancelQueries({
        queryKey: integrationKeys.stravaMappings(),
      });
      const previousMappings =
        queryClient.getQueryData<StravaAthleteMappingListResponse>(
          integrationKeys.stravaMappings()
        );
      if (previousMappings) {
        queryClient.setQueryData<StravaAthleteMappingListResponse>(
          integrationKeys.stravaMappings(),
          {
            ...previousMappings,
            data: previousMappings.data.filter(
              mapping =>
                mapping.attributes.strava_athlete_id !== stravaAthleteId
            ),
          }
        );
      }
      return { previousMappings };
    },
    onError: (error: Error, _stravaAthleteId, context) => {
      if (context?.previousMappings) {
        queryClient.setQueryData(
          integrationKeys.stravaMappings(),
          context.previousMappings
        );
      }
      toast.error(`Failed to delete mapping: ${error.message}`);
    },
    onSuccess: () => {
      toast.success('Mapping deleted successfully');
    },
    onSettled: () => {
      void invalidateAfterMutation(queryClient, {
        queryKey: integrationKeys.stravaMappings(),
      });
    },
  });
}

export async function fetchJournalUnmatchedStravaAthletes(
  journalId: string
): Promise<UnmatchedStravaAthleteListResponse> {
  const response = await fetch(
    `/api/integrations/strava/journals/${journalId}/unmatched-athletes`,
    {
      credentials: 'include',
    }
  );
  return handleApiResponse<UnmatchedStravaAthleteListResponse>(response);
}

export function useJournalUnmatchedStravaAthletes(
  journalId: string,
  enabled: boolean = true
) {
  return useQuery({
    queryKey: integrationKeys.stravaJournalUnmatched(journalId),
    queryFn: () => fetchJournalUnmatchedStravaAthletes(journalId),
    enabled,
    staleTime: 60 * 1000,
  });
}

// Snipe-IT Settings

export interface SnipeItSettings {
  base_url: string;
  snipeit_user_id: string | null;
}

export interface SnipeItSettingsRequest {
  base_url: string;
  snipeit_user_id: string | null;
}

export interface SnipeItSettingsResponse {
  data: {
    id: string;
    type: string;
    attributes: SnipeItSettings;
  };
}

export async function fetchSnipeItSettings(): Promise<SnipeItSettings> {
  const response = await fetch('/api/integrations/snipeit/settings', {
    credentials: 'include',
  });
  const jsonApiRes = await handleApiResponse<SnipeItSettingsResponse>(response);
  return jsonApiRes.data.attributes;
}

export async function saveSnipeItSettings(
  request: SnipeItSettingsRequest
): Promise<SnipeItSettings> {
  const response = await fetch('/api/integrations/snipeit/settings', {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
    },
    credentials: 'include',
    body: JSON.stringify(request),
  });
  const jsonApiRes = await handleApiResponse<SnipeItSettingsResponse>(response);
  return jsonApiRes.data.attributes;
}

export function useSnipeItSettings() {
  return useQuery({
    queryKey: [...integrationKeys.all, 'snipeit', 'settings'],
    queryFn: fetchSnipeItSettings,
    staleTime: 5 * 60 * 1000, // 5 minutes
    retry: false, // Don't retry on 404 (no settings yet)
  });
}

export function useSaveSnipeItSettings() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: saveSnipeItSettings,
    onSuccess: () => {
      void invalidateAfterMutation(
        queryClient,
        { queryKey: [...integrationKeys.all, 'snipeit', 'settings'] },
        { queryKey: integrationKeys.list() }
      );
      toast.success('Snipe-IT settings saved successfully');
    },
    onError: (error: Error) => {
      toast.error(`Failed to save Snipe-IT settings: ${error.message}`);
    },
  });
}

// Snipe-IT API Key Connection

export interface SnipeItConnectRequest {
  api_key: string;
}

export interface SnipeItConnectResponse {
  success: boolean;
  message: string;
}

export interface SnipeItDisconnectResponse {
  success: boolean;
  message: string;
}

export async function connectSnipeIt(
  request: SnipeItConnectRequest
): Promise<SnipeItConnectResponse> {
  const response = await fetch('/api/integrations/snipeit/connect', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    credentials: 'include',
    body: JSON.stringify(request),
  });
  return handleApiResponse<SnipeItConnectResponse>(response);
}

export async function disconnectSnipeIt(): Promise<SnipeItDisconnectResponse> {
  const response = await fetch('/api/integrations/snipeit/connect', {
    method: 'DELETE',
    credentials: 'include',
  });
  return handleApiResponse<SnipeItDisconnectResponse>(response);
}

export function useSnipeItConnect() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: connectSnipeIt,
    onSuccess: (data: SnipeItConnectResponse) => {
      void invalidateAfterMutation(
        queryClient,
        { queryKey: integrationKeys.list() },
        { queryKey: [...integrationKeys.all, 'snipeit', 'settings'] }
      );
      toast.success(data.message);
    },
    onError: (error: Error) => {
      toast.error(`Failed to connect Snipe-IT: ${error.message}`);
    },
  });
}

export function useSnipeItDisconnect() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: disconnectSnipeIt,
    onSuccess: (data: SnipeItDisconnectResponse) => {
      void invalidateAfterMutation(
        queryClient,
        { queryKey: integrationKeys.list() },
        { queryKey: [...integrationKeys.all, 'snipeit', 'settings'] }
      );
      toast.success(data.message);
    },
    onError: (error: Error) => {
      toast.error(`Failed to disconnect Snipe-IT: ${error.message}`);
    },
  });
}

// Webhook Re-registration

/**
 * Re-register webhooks for an integration.
 * - Google: POST /api/integrations/google/webhooks/reregister
 * - Strava: POST /api/integrations/strava/webhooks/reregister
 */
export async function reregisterWebhooks(
  integrationId: string
): Promise<WebhookReregisterResponse> {
  const response = await fetch(
    `/api/integrations/${integrationId}/webhooks/reregister`,
    {
      method: 'POST',
      credentials: 'include',
    }
  );
  return handleApiResponse<WebhookReregisterResponse>(response);
}

export function useReregisterWebhooks(integrationId: string) {
  return useMutation({
    mutationFn: () => reregisterWebhooks(integrationId),
    onSuccess: (data: WebhookReregisterResponse) => {
      toast.success(data.data.attributes.message);
    },
    onError: (error: Error) => {
      toast.error(`Failed to re-register webhooks: ${error.message}`);
    },
  });
}

/**
 * Fetch the webhook URL for Snipe-IT (manual webhook setup).
 * GET /api/integrations/snipeit/webhook-url
 */
export async function fetchSnipeItWebhookUrl(): Promise<WebhookUrlResponse> {
  const response = await fetch('/api/integrations/snipeit/webhook-url', {
    credentials: 'include',
  });
  return handleApiResponse<WebhookUrlResponse>(response);
}

export function useSnipeItWebhookUrl(enabled: boolean = false) {
  return useQuery({
    queryKey: [...integrationKeys.all, 'snipeit', 'webhook-url'],
    queryFn: fetchSnipeItWebhookUrl,
    enabled,
    staleTime: 5 * 60 * 1000, // 5 minutes
  });
}

// Immich API Key Connection

export interface ImmichConnectRequest {
  server_url: string;
  api_key: string;
}

export interface ImmichConnectResponse {
  status: string;
  message: string;
}

export async function connectImmich(
  request: ImmichConnectRequest
): Promise<ImmichConnectResponse> {
  const response = await fetch('/api/integrations/immich/connect', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    credentials: 'include',
    body: JSON.stringify(request),
  });
  return handleApiResponse<ImmichConnectResponse>(response);
}

export async function disconnectImmich(): Promise<void> {
  const response = await fetch('/api/integrations/immich/disconnect', {
    method: 'POST',
    credentials: 'include',
  });

  if (!response.ok) {
    throw new Error('Failed to disconnect Immich');
  }
}

export function useImmichConnect() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: connectImmich,
    onSuccess: (data: ImmichConnectResponse) => {
      void invalidateAfterMutation(queryClient, {
        queryKey: integrationKeys.list(),
      });
      toast.success(data.message || 'Connected to Immich successfully');
    },
    onError: (error: Error) => {
      toast.error(`Failed to connect to Immich: ${error.message}`);
    },
  });
}

export function useImmichDisconnect() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: disconnectImmich,
    onSuccess: () => {
      void invalidateAfterMutation(queryClient, {
        queryKey: integrationKeys.list(),
      });
      toast.success('Disconnected from Immich successfully');
    },
    onError: (error: Error) => {
      toast.error(`Failed to disconnect Immich: ${error.message}`);
    },
  });
}

// Immich Conflict Resolution

export interface ImmichConflictResolveRequest {
  action: 'link' | 'create';
  contact_id?: number;
}

export async function fetchImmichConflicts(): Promise<ImmichConflictListResponse> {
  const response = await fetch('/api/integrations/immich/conflicts', {
    credentials: 'include',
  });
  return handleApiResponse<ImmichConflictListResponse>(response);
}

export async function resolveImmichConflict(
  conflictId: string,
  request: ImmichConflictResolveRequest
): Promise<ImmichConflictResponse> {
  const response = await fetch(
    `/api/integrations/immich/conflicts/${conflictId}/resolve`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      credentials: 'include',
      body: JSON.stringify(request),
    }
  );
  return handleApiResponse<ImmichConflictResponse>(response);
}

export function useImmichConflicts(enabled: boolean = true) {
  return useQuery({
    queryKey: integrationKeys.immichConflicts(),
    queryFn: fetchImmichConflicts,
    enabled,
    staleTime: 30 * 1000, // 30 seconds
  });
}

export function useResolveImmichConflict() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      conflictId,
      request,
    }: {
      conflictId: string;
      request: ImmichConflictResolveRequest;
    }) => resolveImmichConflict(conflictId, request),
    onSuccess: () => {
      void invalidateAfterMutation(queryClient, {
        queryKey: integrationKeys.immichConflicts(),
      });
      toast.success('Conflict resolved successfully');
    },
    onError: (error: Error) => {
      toast.error(`Failed to resolve conflict: ${error.message}`);
    },
  });
}
