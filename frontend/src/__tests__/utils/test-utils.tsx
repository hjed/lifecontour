/**
 * Test utilities for React Testing Library.
 *
 * Provides custom render function with all necessary providers.
 */

import React, { ReactElement } from 'react';
import { render, RenderOptions } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider } from '@/lib/auth-context';

// Mock the API client for tests
jest.mock('@/lib/api-client', () => ({
  apiClient: {
    getAuthStatus: jest.fn().mockResolvedValue({
      data: { authenticated: false, user: null },
    }),
    getAuthProviders: jest.fn().mockResolvedValue({
      data: {
        providers: [
          { name: 'github', display_name: 'GitHub', icon_url: null },
          { name: 'microsoft', display_name: 'Microsoft', icon_url: null },
        ],
      },
    }),
    logout: jest.fn().mockResolvedValue({ data: { message: 'Logged out' } }),
    getContacts: jest.fn().mockResolvedValue({ data: [] }),
    searchContacts: jest.fn().mockResolvedValue({ data: { hits: [] } }),
    globalSearch: jest
      .fn()
      .mockResolvedValue({ data: { contacts: { hits: [], total: 0 } } }),
    getHealth: jest.fn().mockResolvedValue({ data: { status: 'healthy' } }),
  },
}));

// Mock Next.js router
jest.mock('next/navigation', () => ({
  useRouter: () => ({
    push: jest.fn(),
    replace: jest.fn(),
    back: jest.fn(),
    forward: jest.fn(),
    refresh: jest.fn(),
    prefetch: jest.fn(),
  }),
  useSearchParams: () => ({
    get: jest.fn().mockReturnValue(null),
  }),
  usePathname: () => '/',
}));

// Create a custom render function that includes providers
const AllTheProviders = ({ children }: { children: React.ReactNode }) => {
  // Create a new QueryClient for each test to avoid state leakage
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false, // Disable retries in tests
        staleTime: 0,
        gcTime: 0,
      },
      mutations: {
        retry: false,
      },
    },
  });

  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>{children}</AuthProvider>
    </QueryClientProvider>
  );
};

const customRender = (
  ui: ReactElement,
  options?: Omit<RenderOptions, 'wrapper'>
) => render(ui, { wrapper: AllTheProviders, ...options });

// Re-export everything
export * from '@testing-library/react';
export { userEvent };

// Override render method
export { customRender as render };

// Test utilities for authentication
export const mockAuthenticatedUser = {
  id: 'test-user-123',
  email: 'test@example.com',
  name: 'Test User',
  provider: 'github',
};

export const mockUnauthenticatedState = {
  authenticated: false,
  user: undefined,
};

export const mockAuthenticatedState = {
  authenticated: true,
  user: mockAuthenticatedUser,
};

// Helper to mock authenticated state
export const mockAuthenticated = async () => {
  const { apiClient } = await import('@/lib/api-client');
  (
    apiClient.getAuthStatus as jest.MockedFunction<
      typeof apiClient.getAuthStatus
    >
  ).mockResolvedValue({
    data: mockAuthenticatedState,
  });
};

// Helper to mock unauthenticated state
export const mockUnauthenticated = async () => {
  const { apiClient } = await import('@/lib/api-client');
  (
    apiClient.getAuthStatus as jest.MockedFunction<
      typeof apiClient.getAuthStatus
    >
  ).mockResolvedValue({
    data: mockUnauthenticatedState,
  });
};

// Helper to wait for async operations
export const waitForAsync = () =>
  new Promise(resolve => setTimeout(resolve, 0));
