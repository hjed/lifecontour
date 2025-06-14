/**
 * Common test utilities to reduce duplication across test files.
 *
 * Provides reusable components and mock setups following
 * SonarQube quality standards.
 */

import { render, RenderOptions } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider } from '@/lib/auth/AuthProvider';
import { ReactElement } from 'react';
import { ContactMethodType } from '@/types/contacts';

// Test constants to avoid string duplication
export const TEST_CONSTANTS = {
  OAUTH_URLS: {
    GITHUB: 'https://github.com/login/oauth/authorize?client_id=test',
    MICROSOFT: 'https://login.microsoftonline.com/oauth2/v2.0/authorize',
    DISCORD: 'https://discord.com/api/oauth2/authorize',
  },
  ERROR_MESSAGES: {
    OAUTH_NOT_CONFIGURED: 'OAuth provider not configured',
    TEST_ERROR: 'Test error',
    LOGIN_FAILED: 'Login failed',
  },
  BUTTON_LABELS: {
    GITHUB: /continue with github/i,
    MICROSOFT: /continue with microsoft/i,
    DISCORD: /continue with discord/i,
  },
  TEST_IDS: {
    AUTH_STATUS: 'auth-status',
    LOADING_STATUS: 'loading-status',
    USER_INFO: 'user-info',
    ERROR_MESSAGE: 'error-message',
    LOGIN_GITHUB: 'login-github',
    LOGOUT: 'logout',
    CLEAR_ERROR: 'clear-error',
  },
} as const;

// Mock response factories to reduce duplication
export const createMockResponses = {
  sessionNotAuthenticated: () => ({
    ok: false,
    status: 401,
  }),

  loginSuccess: (provider: 'github' | 'microsoft' | 'discord') => ({
    ok: true,
    json: async () => ({
      authorize_url:
        TEST_CONSTANTS.OAUTH_URLS[
          provider.toUpperCase() as keyof typeof TEST_CONSTANTS.OAUTH_URLS
        ],
      state: 'test-state',
    }),
  }),

  loginError: (
    message: string = TEST_CONSTANTS.ERROR_MESSAGES.OAUTH_NOT_CONFIGURED
  ) => ({
    ok: false,
    json: async () => ({
      errors: [{ detail: message }],
    }),
  }),

  logoutSuccess: () => ({
    ok: true,
    json: async () => ({ success: true }),
  }),

  withDelay: (response: unknown, delay: number = 100) =>
    new Promise(resolve => setTimeout(() => resolve(response), delay)),
} as const;

// Test wrapper component with providers
interface TestWrapperProps {
  children: React.ReactNode;
}

function TestWrapper({ children }: TestWrapperProps) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>{children}</AuthProvider>
    </QueryClientProvider>
  );
}

// Custom render function with providers
interface CustomRenderOptions extends Omit<RenderOptions, 'wrapper'> {
  wrapper?: React.ComponentType<{ children: React.ReactNode }>;
}

export function renderWithProviders(
  ui: ReactElement,
  options?: CustomRenderOptions
) {
  return render(ui, {
    wrapper: TestWrapper,
    ...options,
  });
}

// Mock setup utilities
export const setupMocks = {
  fetch: () => {
    global.fetch = jest.fn();
  },

  windowLocation: () => {
    delete (window as unknown as { location?: unknown }).location;
    (window as unknown as { location: { href: string } }).location = {
      href: '',
    };
  },

  clearMocks: () => {
    jest.clearAllMocks();
    localStorage.clear();
  },
} as const;

// Contact-specific test utilities
export const contactTestUtils = {
  // Common beforeEach setup for contact tests
  setupContactTest: () => {
    jest.clearAllMocks();
    setupMocks.windowLocation();
  },

  // Mock data factories for contacts
  createMockContact: (overrides: Partial<any> = {}) => {
    const baseContact = {
      id: '1',
      type: 'contacts',
      attributes: {
        first_name: 'John',
        last_name: 'Doe',
        middle_name: '',
        nick_name: '',
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-01T00:00:00Z',
        contact_methods: [
          {
            id: '1',
            type: 'contact_methods',
            attributes: {
              method_type: ContactMethodType.EMAIL,
              value: 'john@example.com',
              label: 'Work',
              is_primary: true,
            },
          },
        ],
        addresses: [],
        notes: [],
      },
      relationships: {
        tags: {
          data: [],
        },
      },
    };

    return {
      ...baseContact,
      ...overrides,
      attributes: {
        ...baseContact.attributes,
        ...overrides.attributes,
      },
    };
  },

  createMockContactsResponse: (contacts: any[] = [], total?: number) => ({
    data:
      contacts.length > 0 ? contacts : [contactTestUtils.createMockContact()],
    meta: {
      total: total ?? (contacts.length > 0 ? contacts.length : 1),
      page: 1,
      per_page: 20,
      total_pages: Math.ceil(
        (total ?? (contacts.length > 0 ? contacts.length : 1)) / 20
      ),
    },
  }),

  createEmptyContactsResponse: () => ({
    data: [],
    meta: {
      total: 0,
      page: 1,
      per_page: 20,
      total_pages: 0,
    },
  }),

  createMockContactResponse: (contact?: any) => ({
    data:
      contact ||
      contactTestUtils.createMockContact({
        attributes: {
          middle_name: 'William',
          nick_name: 'Johnny',
        },
      }),
  }),
} as const;

// Common test patterns
export const testPatterns = {
  expectAuthStatus: (status: 'authenticated' | 'not-authenticated') => {
    const element = document.querySelector(
      `[data-testid="${TEST_CONSTANTS.TEST_IDS.AUTH_STATUS}"]`
    );
    expect(element).toHaveTextContent(status);
  },

  expectLoadingStatus: (status: 'loading' | 'not-loading') => {
    const element = document.querySelector(
      `[data-testid="${TEST_CONSTANTS.TEST_IDS.LOADING_STATUS}"]`
    );
    expect(element).toHaveTextContent(status);
  },

  expectErrorMessage: (message: string) => {
    const element = document.querySelector(
      `[data-testid="${TEST_CONSTANTS.TEST_IDS.ERROR_MESSAGE}"]`
    );
    expect(element).toHaveTextContent(message);
  },
} as const;

// Re-export testing library utilities
export * from '@testing-library/react';
export { userEvent } from '@testing-library/user-event';
