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
  useGoogleContactsSync,
  useGoogleContactsStatus,
  useSyncJobStatus,
  useIntegrationHealth,
  fetchGoogleContactsStatus,
  fetchSyncJobStatus,
  fetchIntegrationHealth,
  triggerGoogleContactsSync,
} from '../integrations';

// Mock fetch globally
global.fetch = jest.fn();
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

  describe('fetchGoogleContactsStatus', () => {
    it('should fetch Google Contacts integration status', async () => {
      const mockResponse = {
        data: {
          id: 'google-contacts',
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

      const result = await fetchGoogleContactsStatus();

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

      await expect(fetchGoogleContactsStatus()).rejects.toThrow(
        'Authentication required'
      );
    });
  });

  describe('triggerGoogleContactsSync', () => {
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

      const result = await triggerGoogleContactsSync();

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

      const result = await triggerGoogleContactsSync('full');

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

  describe('useGoogleContactsStatus', () => {
    it('should fetch and return Google Contacts status', async () => {
      const mockResponse = {
        data: {
          id: 'google-contacts',
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
      const { result } = renderHook(() => useGoogleContactsStatus(), {
        wrapper,
      });

      await waitFor(() => {
        expect(result.current.isSuccess).toBe(true);
      });

      expect(result.current.data).toEqual(mockResponse);
    });
  });

  describe('useGoogleContactsSync', () => {
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
      const { result } = renderHook(() => useGoogleContactsSync(), { wrapper });

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
});
