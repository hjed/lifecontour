/**
 * @jest-environment jsdom
 */

/**
 * Tests for integrations page.
 *
 * Tests the main integrations page including Google Contacts integration
 * status display, sync controls, and health monitoring.
 */

import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import IntegrationsPage from '../page';

// Mock the API hooks
jest.mock('@/lib/api/integrations', () => ({
  useGoogleContactsStatus: jest.fn(),
  useGoogleContactsSync: jest.fn(),
  useIntegrationHealth: jest.fn(),
  useSyncHistory: jest.fn(),
}));

// Mock toast
jest.mock('sonner', () => ({
  toast: {
    success: jest.fn(),
    error: jest.fn(),
  },
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

// Get the mocked functions
const useGoogleContactsStatus = jest.fn();
const useGoogleContactsSync = jest.fn();
const useIntegrationHealth = jest.fn();
const useSyncHistory = jest.fn();

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  const TestWrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );

  return TestWrapper;
}

describe('IntegrationsPage', () => {
  beforeEach(() => {
    jest.clearAllMocks();

    // Default mock implementations
    useGoogleContactsStatus.mockReturnValue({
      data: {
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
      },
      isLoading: false,
      error: null,
    });

    useGoogleContactsSync.mockReturnValue({
      mutate: jest.fn(),
      isPending: false,
      error: null,
    });

    useIntegrationHealth.mockReturnValue({
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
    });

    useSyncHistory.mockReturnValue({
      data: {
        data: [
          {
            id: 'job-1',
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
        ],
        meta: { total: 1, page: 1, pageSize: 10 },
      },
      isLoading: false,
      error: null,
    });
  });

  it('should render integrations page with title', () => {
    const wrapper = createWrapper();
    render(<IntegrationsPage />, { wrapper });

    expect(screen.getByText('Integrations')).toBeInTheDocument();
    expect(
      screen.getByText(/Manage your external integrations/)
    ).toBeInTheDocument();
  });

  it('should display Google Contacts integration section', () => {
    const wrapper = createWrapper();
    render(<IntegrationsPage />, { wrapper });

    expect(
      screen.getByTestId('google-contacts-integration')
    ).toBeInTheDocument();
    expect(screen.getByText('Google Contacts')).toBeInTheDocument();
  });

  it('should show connected status when integration is connected', () => {
    const wrapper = createWrapper();
    render(<IntegrationsPage />, { wrapper });

    expect(screen.getByText('Connected')).toBeInTheDocument();
    expect(screen.getByText('150 contacts synced')).toBeInTheDocument();
  });

  it('should display sync trigger buttons', () => {
    const wrapper = createWrapper();
    render(<IntegrationsPage />, { wrapper });

    expect(screen.getByTestId('trigger-google-sync')).toBeInTheDocument();
    expect(screen.getByText('Smart Sync')).toBeInTheDocument();
  });

  it('should trigger sync when sync button is clicked', async () => {
    const mockMutate = jest.fn();
    useGoogleContactsSync.mockReturnValue({
      mutate: mockMutate,
      isPending: false,
      error: null,
    });

    const wrapper = createWrapper();
    render(<IntegrationsPage />, { wrapper });

    const syncButton = screen.getByTestId('trigger-google-sync');
    fireEvent.click(syncButton);

    await waitFor(() => {
      expect(mockMutate).toHaveBeenCalledWith('smart');
    });
  });

  it('should display integration status', () => {
    const wrapper = createWrapper();
    render(<IntegrationsPage />, { wrapper });

    expect(screen.getByTestId('integration-status')).toBeInTheDocument();
  });

  it('should display sync history', () => {
    const wrapper = createWrapper();
    render(<IntegrationsPage />, { wrapper });

    expect(screen.getByTestId('sync-history')).toBeInTheDocument();
    expect(screen.getByText('Recent Sync Jobs')).toBeInTheDocument();
  });

  it('should show loading state when data is loading', () => {
    useGoogleContactsStatus.mockReturnValue({
      data: null,
      isLoading: true,
      error: null,
    });

    const wrapper = createWrapper();
    render(<IntegrationsPage />, { wrapper });

    expect(screen.getByTestId('loading-spinner')).toBeInTheDocument();
  });

  it('should show error state when there is an error', () => {
    useGoogleContactsStatus.mockReturnValue({
      data: null,
      isLoading: false,
      error: new Error('Failed to fetch status'),
    });

    const wrapper = createWrapper();
    render(<IntegrationsPage />, { wrapper });

    expect(screen.getByText(/Failed to fetch status/)).toBeInTheDocument();
  });

  it('should show disconnected state when integration is not connected', () => {
    useGoogleContactsStatus.mockReturnValue({
      data: {
        data: {
          id: 'google-contacts',
          type: 'integration-status',
          attributes: {
            connected: false,
            lastSync: null,
            syncCount: 0,
            status: 'disconnected',
          },
        },
      },
      isLoading: false,
      error: null,
    });

    const wrapper = createWrapper();
    render(<IntegrationsPage />, { wrapper });

    expect(screen.getByText('Disconnected')).toBeInTheDocument();
    expect(screen.getByText('Connect Google Account')).toBeInTheDocument();
  });

  it('should display health indicators', () => {
    const wrapper = createWrapper();
    render(<IntegrationsPage />, { wrapper });

    expect(screen.getByText('System Health')).toBeInTheDocument();
    expect(screen.getByText('Redis: healthy')).toBeInTheDocument();
    expect(screen.getByText('Worker: healthy')).toBeInTheDocument();
  });

  it('should show sync progress when sync is running', () => {
    useGoogleContactsSync.mockReturnValue({
      mutate: jest.fn(),
      isPending: true,
      error: null,
    });

    const wrapper = createWrapper();
    render(<IntegrationsPage />, { wrapper });

    expect(screen.getByTestId('sync-progress')).toBeInTheDocument();
  });
});
