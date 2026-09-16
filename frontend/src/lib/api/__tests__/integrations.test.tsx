/**
 * @jest-environment jsdom
 */

/**
 * Tests for integration API client functions.
 *
 * Tests the integration API functions including sync triggers,
 * status monitoring, and job tracking.
 */

import React, { ReactNode } from 'react';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import {
  useGoogleSync,
  useGoogleStatus,
  useSyncJobStatus,
  useIntegrationHealth,
  fetchGoogleStatus,
  fetchSyncJobStatus,
  fetchIntegrationHealth,
  triggerGoogleSync,
  useDeleteStravaMapping,
  integrationKeys,
  rotateSnipeItWebhookUrl,
  fetchSnipeItWebhookUrl,
  useRotateSnipeItWebhookUrl,
} from '../integrations';
import { WebhookUrlResponse } from '@/types/integrations';

// Mock fetch globally
globalThis.fetch = jest.fn() as unknown as typeof fetch;
const mockFetch = fetch as jest.MockedFunction<typeof fetch>;

// Mock toast
jest.mock('sonner', () => ({
  toast: {
    success: jest.fn(),
    error: jest.fn(),
  },
}));

// Test wrapper with QueryClient
function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  const TestWrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );

  return TestWrapper;
}

describe('Integration API Functions', () => {
  beforeEach(() => {
    mockFetch.mockClear();
  });

  describe('fetchGoogleStatus', () => {
    it('should fetch Google Contacts integration status', async () => {
      const mockResponse = {
        data: {
          id: 'google',
          type: 'integration-status',
          attributes: {
            connected: true,
            lastSync: '2024-01-15T10:30:00Z',
            syncCount: 150,
            status: 'active',
          },
        },
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse,
      } as Response);

      const result = await fetchGoogleStatus();

      expect(mockFetch).toHaveBeenCalledWith(
        '/api/integrations/google/contacts/status',
        {
          credentials: 'include',
        }
      );
      expect(result).toEqual(mockResponse);
    });

    it('should handle API errors', async () => {
      const mockError = {
        errors: [
          {
            status: '401',
            title: 'Unauthorized',
            detail: 'Authentication required',
          },
        ],
      };

      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 401,
        json: async () => mockError,
      } as Response);

      await expect(fetchGoogleStatus()).rejects.toThrow('HTTP 401: undefined');
    });
  });

  describe('triggerGoogleSync', () => {
    it('should trigger smart sync by default', async () => {
      const mockResponse = {
        data: {
          id: 'job-123',
          type: 'sync-job',
          attributes: {
            status: 'queued',
            syncType: 'smart',
            createdAt: '2024-01-15T10:30:00Z',
          },
        },
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse,
      } as Response);

      const result = await triggerGoogleSync();

      expect(mockFetch).toHaveBeenCalledWith(
        '/api/integrations/google/contacts/sync',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ sync_type: 'smart' }),
        }
      );
      expect(result).toEqual(mockResponse);
    });

    it('should trigger full sync when specified', async () => {
      const mockResponse = {
        data: {
          id: 'job-456',
          type: 'sync-job',
          attributes: {
            status: 'queued',
            syncType: 'full',
            createdAt: '2024-01-15T10:30:00Z',
          },
        },
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse,
      } as Response);

      const result = await triggerGoogleSync('full');

      expect(mockFetch).toHaveBeenCalledWith(
        '/api/integrations/google/contacts/sync',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ sync_type: 'full' }),
        }
      );
      expect(result).toEqual(mockResponse);
    });
  });

  describe('fetchSyncJobStatus', () => {
    it('should fetch sync job status', async () => {
      const mockResponse = {
        data: {
          id: 'job-123',
          type: 'sync-job',
          attributes: {
            status: 'completed',
            syncType: 'smart',
            createdAt: '2024-01-15T10:30:00Z',
            completedAt: '2024-01-15T10:32:00Z',
            contactsProcessed: 25,
            contactsCreated: 5,
            contactsUpdated: 3,
          },
        },
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse,
      } as Response);

      const result = await fetchSyncJobStatus('job-123');

      expect(mockFetch).toHaveBeenCalledWith(
        '/api/integrations/google/contacts/sync/job-123',
        {
          credentials: 'include',
        }
      );
      expect(result).toEqual(mockResponse);
    });
  });

  describe('fetchIntegrationHealth', () => {
    it('should fetch integration health status', async () => {
      const mockResponse = {
        data: {
          id: 'health',
          type: 'integration-health',
          attributes: {
            redis: { status: 'healthy', latency: 5 },
            worker: { status: 'healthy', lastSeen: '2024-01-15T10:30:00Z' },
            overall: 'healthy',
          },
        },
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse,
      } as Response);

      const result = await fetchIntegrationHealth();

      expect(mockFetch).toHaveBeenCalledWith('/api/integrations/health', {
        credentials: 'include',
      });
      expect(result).toEqual(mockResponse);
    });
  });
});

describe('Integration React Query Hooks', () => {
  beforeEach(() => {
    mockFetch.mockClear();
  });

  describe('useGoogleStatus', () => {
    it('should fetch and return Google Contacts status', async () => {
      const mockResponse = {
        data: {
          id: 'google',
          type: 'integration-status',
          attributes: {
            connected: true,
            lastSync: '2024-01-15T10:30:00Z',
            syncCount: 150,
            status: 'active',
          },
        },
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse,
      } as Response);

      const wrapper = createWrapper();
      const { result } = renderHook(() => useGoogleStatus(), {
        wrapper,
      });

      await waitFor(() => {
        expect(result.current.isSuccess).toBe(true);
      });

      expect(result.current.data).toEqual(mockResponse);
    });
  });

  describe('useGoogleSync', () => {
    it('should trigger sync and return job data', async () => {
      const mockResponse = {
        data: {
          id: 'job-123',
          type: 'sync-job',
          attributes: {
            status: 'queued',
            syncType: 'smart',
            createdAt: '2024-01-15T10:30:00Z',
          },
        },
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse,
      } as Response);

      const wrapper = createWrapper();
      const { result } = renderHook(() => useGoogleSync(), { wrapper });

      result.current.mutate('smart');

      await waitFor(() => {
        expect(result.current.isSuccess).toBe(true);
      });

      expect(result.current.data).toEqual(mockResponse);
    });
  });

  describe('useSyncJobStatus', () => {
    it('should fetch sync job status when job ID provided', async () => {
      const mockResponse = {
        data: {
          id: 'job-123',
          type: 'sync-job',
          attributes: {
            status: 'completed',
            syncType: 'smart',
            createdAt: '2024-01-15T10:30:00Z',
            completedAt: '2024-01-15T10:32:00Z',
            contactsProcessed: 25,
          },
        },
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse,
      } as Response);

      const wrapper = createWrapper();
      const { result } = renderHook(() => useSyncJobStatus('job-123'), {
        wrapper,
      });

      await waitFor(() => {
        expect(result.current.isSuccess).toBe(true);
      });

      expect(result.current.data).toEqual(mockResponse);
    });

    it('should not fetch when job ID is null', () => {
      const wrapper = createWrapper();
      const { result } = renderHook(() => useSyncJobStatus(null), { wrapper });

      expect(result.current.data).toBeUndefined();
      expect(mockFetch).not.toHaveBeenCalled();
    });
  });

  describe('useIntegrationHealth', () => {
    it('should fetch integration health status', async () => {
      const mockResponse = {
        data: {
          id: 'health',
          type: 'integration-health',
          attributes: {
            redis: { status: 'healthy', latency: 5 },
            worker: { status: 'healthy', lastSeen: '2024-01-15T10:30:00Z' },
            overall: 'healthy',
          },
        },
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse,
      } as Response);

      const wrapper = createWrapper();
      const { result } = renderHook(() => useIntegrationHealth(), { wrapper });

      await waitFor(() => {
        expect(result.current.isSuccess).toBe(true);
      });

      expect(result.current.data).toEqual(mockResponse);
    });
  });

  describe('useDeleteStravaMapping optimistic updates', () => {
    function createWrapperWithClient() {
      const queryClient = new QueryClient({
        defaultOptions: {
          queries: { retry: false },
          mutations: { retry: false },
        },
      });
      const TestWrapper = ({ children }: { children: ReactNode }) => (
        <QueryClientProvider client={queryClient}>
          {children}
        </QueryClientProvider>
      );
      return { queryClient, TestWrapper };
    }

    const seed = (queryClient: QueryClient) =>
      queryClient.setQueryData(integrationKeys.stravaMappings(), {
        data: [
          {
            id: 'm1',
            type: 'strava-athlete-mapping',
            attributes: {
              strava_athlete_id: 'a1',
              strava_athlete_name: 'Speedy',
              contact_id: 1,
            },
          },
          {
            id: 'm2',
            type: 'strava-athlete-mapping',
            attributes: {
              strava_athlete_id: 'a2',
              strava_athlete_name: 'Keep',
              contact_id: 2,
            },
          },
        ],
      });

    it('removes the mapping row before the request resolves', async () => {
      const { queryClient, TestWrapper } = createWrapperWithClient();
      seed(queryClient);

      let resolveFetch: (value: Response) => void = () => {};
      mockFetch.mockReturnValueOnce(
        new Promise<Response>(resolve => {
          resolveFetch = resolve;
        })
      );

      const { result } = renderHook(() => useDeleteStravaMapping(), {
        wrapper: TestWrapper,
      });

      result.current.mutate('a1');

      await waitFor(() => {
        const cached = queryClient.getQueryData(
          integrationKeys.stravaMappings()
        ) as { data: { attributes: { strava_athlete_id: string } }[] };
        expect(cached.data.map(m => m.attributes.strava_athlete_id)).toEqual([
          'a2',
        ]);
      });

      resolveFetch({ ok: true } as Response);
    });

    it('rolls back the mapping row when the delete fails', async () => {
      const { queryClient, TestWrapper } = createWrapperWithClient();
      seed(queryClient);

      mockFetch.mockResolvedValueOnce({
        ok: false,
        json: async () => ({ errors: [{ detail: 'Boom' }] }),
      } as Response);

      const { result } = renderHook(() => useDeleteStravaMapping(), {
        wrapper: TestWrapper,
      });

      await expect(result.current.mutateAsync('a1')).rejects.toThrow();

      const cached = queryClient.getQueryData(
        integrationKeys.stravaMappings()
      ) as { data: { attributes: { strava_athlete_id: string } }[] };
      expect(cached.data.map(m => m.attributes.strava_athlete_id)).toEqual([
        'a1',
        'a2',
      ]);
    });
  });
});

describe('Snipe-IT webhook URL rotation', () => {
  const rotatedUrl: WebhookUrlResponse = {
    data: {
      type: 'webhook-url',
      attributes: {
        webhook_url: 'https://pms.example/api/integrations/snipeit/webhook/new',
        message: 'Configure this URL in your Snipe-IT instance.',
      },
    },
  };

  beforeEach(() => {
    mockFetch.mockClear();
  });

  it('POSTs to the rotate endpoint and returns the new URL', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => rotatedUrl,
    } as Response);

    const result = await rotateSnipeItWebhookUrl();

    expect(mockFetch).toHaveBeenCalledWith(
      '/api/integrations/snipeit/webhook-url/rotate',
      { method: 'POST', credentials: 'include' }
    );
    expect(result).toEqual(rotatedUrl);
  });

  it('shows the new URL from the cache once rotation succeeds', async () => {
    const queryClient = new QueryClient({
      defaultOptions: { mutations: { retry: false } },
    });
    queryClient.setQueryData(integrationKeys.snipeItWebhookUrl(), {
      data: {
        ...rotatedUrl.data,
        attributes: {
          ...rotatedUrl.data.attributes,
          webhook_url:
            'https://pms.example/api/integrations/snipeit/webhook/old',
        },
      },
    });
    const TestWrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => rotatedUrl,
    } as Response);

    const { result } = renderHook(() => useRotateSnipeItWebhookUrl(), {
      wrapper: TestWrapper,
    });
    await result.current.mutateAsync();

    expect(
      queryClient.getQueryData(integrationKeys.snipeItWebhookUrl())
    ).toEqual(rotatedUrl);
  });

  it('keeps the rotated URL when an earlier URL request finishes afterwards', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    const TestWrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
    const staleUrl: WebhookUrlResponse = {
      data: {
        ...rotatedUrl.data,
        attributes: {
          ...rotatedUrl.data.attributes,
          webhook_url:
            'https://pms.example/api/integrations/snipeit/webhook/old',
        },
      },
    };
    let resolveInitialRequest: (response: Response) => void = () => {};
    mockFetch.mockImplementation(input =>
      String(input).endsWith('/rotate')
        ? Promise.resolve({
            ok: true,
            json: async () => rotatedUrl,
          } as Response)
        : new Promise<Response>(resolve => {
            resolveInitialRequest = resolve;
          })
    );

    // The dialog's first URL request is still in flight when the user rotates.
    const initialRequest = queryClient
      .fetchQuery({
        queryKey: integrationKeys.snipeItWebhookUrl(),
        queryFn: fetchSnipeItWebhookUrl,
      })
      .catch(() => undefined);
    const { result } = renderHook(() => useRotateSnipeItWebhookUrl(), {
      wrapper: TestWrapper,
    });
    await result.current.mutateAsync();
    resolveInitialRequest({ ok: true, json: async () => staleUrl } as Response);
    await initialRequest;

    expect(
      queryClient.getQueryData(integrationKeys.snipeItWebhookUrl())
    ).toEqual(rotatedUrl);
    mockFetch.mockReset();
  });
});
