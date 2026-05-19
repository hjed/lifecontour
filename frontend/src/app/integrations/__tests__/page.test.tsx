/**
 * @jest-environment jsdom
 */

import React from 'react';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import IntegrationsPage from '../page';
import {
  useIntegrations,
  useIntegrationHealth,
  useConsumerLag,
  useSyncHistory,
  useOAuthAuthorize,
  useOAuthDisconnect,
  useGenericSync,
  useDeadLetters,
} from '@/lib/api/integrations';

// Mock the API hooks
jest.mock('@/lib/api/integrations', () => ({
  useIntegrations: jest.fn(),
  useIntegrationHealth: jest.fn(),
  useConsumerLag: jest.fn(),
  useSyncHistory: jest.fn(),
  useOAuthAuthorize: jest.fn(),
  useOAuthCallback: jest.fn(),
  useOAuthDisconnect: jest.fn(),
  useGenericSync: jest.fn(),
  useDeadLetters: jest.fn(),
}));

// Mock AuthGuard
jest.mock('@/components/auth/AuthGuard', () => ({
  AuthGuard: function MockAuthGuard({
    children,
  }: {
    children: React.ReactNode;
  }) {
    return <div data-testid='auth-guard'>{children}</div>;
  },
}));

// Import the mocked functions
const mockUseIntegrations = jest.mocked(useIntegrations);
const mockUseIntegrationHealth = jest.mocked(useIntegrationHealth);
const mockUseConsumerLag = jest.mocked(useConsumerLag);
const mockUseSyncHistory = jest.mocked(useSyncHistory);
const mockUseOAuthAuthorize = jest.mocked(useOAuthAuthorize);
const mockUseOAuthDisconnect = jest.mocked(useOAuthDisconnect);
const mockUseGenericSync = jest.mocked(useGenericSync);
const mockUseDeadLetters = jest.mocked(useDeadLetters);

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });

  return function TestWrapper({ children }: { children: React.ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
  };
}

describe('IntegrationsPage', () => {
  beforeEach(() => {
    jest.clearAllMocks();

    mockUseIntegrations.mockReturnValue({
      data: {
        data: [
          {
            id: 'google',
            type: 'integration',
            attributes: {
              name: 'Google',
              connected: true,
              capabilities: ['contacts_sync', 'calendar_sync'],
              status: 'connected',
              sync_summary: {
                sync_count: 150,
                last_sync_time: '2024-01-15T10:30:00Z',
              },
              needs_reauth: false,
              needs_reconsent: false,
              oauth_authorize_url: '/api/integrations/google/oauth/authorize',
            },
          },
        ],
      },
      isLoading: false,
      error: null,
    } as unknown as ReturnType<typeof useIntegrations>);

    mockUseIntegrationHealth.mockReturnValue({
      data: {
        data: {
          id: 'health',
          type: 'integration-health',
          attributes: {
            redis: { status: 'healthy', latency: 5 },
            worker: { status: 'healthy', lastSeen: '2024-01-15T10:30:00Z' },
            overall: 'healthy',
            lastChecked: '2024-01-15T10:30:00Z',
          },
        },
      },
      isLoading: false,
      error: null,
    } as unknown as ReturnType<typeof useIntegrationHealth>);

    mockUseConsumerLag.mockReturnValue({
      data: [],
      isLoading: false,
      error: null,
    } as unknown as ReturnType<typeof useConsumerLag>);

    mockUseSyncHistory.mockReturnValue({
      data: {
        data: [],
        meta: { total: 0, page: 1, pageSize: 10 },
      },
      isLoading: false,
      error: null,
    } as unknown as ReturnType<typeof useSyncHistory>);

    mockUseOAuthAuthorize.mockReturnValue({
      mutate: jest.fn(),
      isPending: false,
      error: null,
    } as unknown as ReturnType<typeof useOAuthAuthorize>);

    mockUseOAuthDisconnect.mockReturnValue({
      mutate: jest.fn(),
      isPending: false,
      error: null,
    } as unknown as ReturnType<typeof useOAuthDisconnect>);

    mockUseGenericSync.mockReturnValue({
      mutate: jest.fn(),
      isPending: false,
      error: null,
    } as unknown as ReturnType<typeof useGenericSync>);

    mockUseDeadLetters.mockReturnValue({
      data: {
        items: [],
        total: 0,
        limit: 10,
        offset: 0,
      },
      isLoading: false,
      error: null,
    } as unknown as ReturnType<typeof useDeadLetters>);
  });

  it('should render integrations page with title', () => {
    const wrapper = createWrapper();
    render(<IntegrationsPage />, { wrapper });

    expect(screen.getByText('Integrations')).toBeInTheDocument();
  });

  it('should render integration panels', () => {
    const wrapper = createWrapper();
    render(<IntegrationsPage />, { wrapper });

    expect(screen.getByTestId('integration-panel-google')).toBeInTheDocument();
  });

  it('should show loading state when data is loading', () => {
    mockUseIntegrations.mockReturnValue({
      data: undefined,
      isLoading: true,
      error: null,
    } as never);

    const wrapper = createWrapper();
    render(<IntegrationsPage />, { wrapper });

    expect(screen.getByTestId('loading-spinner')).toBeInTheDocument();
  });
});
