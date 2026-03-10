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
import {
  ContactMethodType,
  ContactResource,
  ContactListResponse,
} from '@/types/contacts';

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
  readonly children: React.ReactNode;
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

// Note: Mock constants are now centralized in jest.setup.ts to avoid duplication

// Mock setup utilities
export const setupMocks = {
  fetch: () => {
    globalThis.fetch = jest.fn();
  },

  windowLocation: () => {
    // In Jest 30 with JSDOM v21+, window.location is non-configurable.
    // We can't replace it, but we can suppress the "Not implemented: navigation" errors
    // by listening to href changes and preventing actual navigation.
    // Tests should use the mocked Next.js router for navigation assertions when possible.
    // This is a no-op as JSDOM v21+ properly handles location.href setting without
    // needing manual mocking - tests should check for navigation via mocked router
    // or use waitFor to handle async navigation behavior.
  },

  clearMocks: () => {
    jest.clearAllMocks();
    localStorage.clear();
  },

  constants: () => {
    // No-op: constants are mocked globally in jest.setup.ts
  },

  // Common API hook mocks to reduce duplication
  contactsApi: () => {
    jest.mock('@/lib/api/contacts', () => ({
      useContacts: jest.fn(),
      useContact: jest.fn(),
      useSearchContacts: jest.fn(),
      useCreateContact: jest.fn(),
      useUpdateContact: jest.fn(),
      useDeleteContact: jest.fn(),
      useToggleContactFavourite: jest.fn(),
      useTags: jest.fn(),
    }));
  },

  // Common Next.js navigation mocks
  nextNavigation: (
    overrides: {
      router?: Record<string, unknown>;
      pathname?: string;
      params?: Record<string, unknown>;
      [key: string]: unknown;
    } = {}
  ) => {
    const baseRouter = {
      push: jest.fn(),
      replace: jest.fn(),
      prefetch: jest.fn(),
      back: jest.fn(),
      forward: jest.fn(),
      refresh: jest.fn(),
    };
    const router = overrides.router
      ? { ...baseRouter, ...overrides.router }
      : baseRouter;

    jest.mock('next/navigation', () => ({
      useRouter: () => router,
      usePathname: () => overrides.pathname || '/contacts',
      useSearchParams: () => new URLSearchParams(),
      useParams: () => overrides.params || {},
      ...overrides,
    }));
  },

  // Common date-fns mocks
  dateFns: () => {
    jest.mock('date-fns', () => ({
      format: jest.fn(() => '1 January 2024'),
    }));
    jest.mock('date-fns/locale', () => ({
      enAU: {},
    }));
  },

  // Common debounce hook mock
  debounce: () => {
    jest.mock('@/hooks/useDebounce', () => ({
      useDebounce: jest.fn(value => value),
    }));
  },

  // Common breadcrumb test setup
  breadcrumb: () => {
    const mockUsePathname = jest.fn();
    jest.mock('next/navigation', () => ({
      usePathname: mockUsePathname,
    }));
    return { mockUsePathname };
  },
} as const;

// Breadcrumb test utilities to reduce duplication
export const breadcrumbTestUtils = {
  // Common setup for breadcrumb tests
  setupBreadcrumbTest: () => {
    const { mockUsePathname } = setupMocks.breadcrumb();
    mockUsePathname.mockReturnValue('/contacts');

    const cleanup = () => {
      jest.clearAllMocks();
    };

    return { mockUsePathname, cleanup };
  },

  // Common test patterns for breadcrumb rendering
  expectBreadcrumbNavigation: (name = 'Breadcrumb navigation') => {
    const nav = document.querySelector(
      `[role="navigation"][aria-label="${name}"]`
    );
    expect(nav).toBeInTheDocument();
    return nav;
  },

  expectBreadcrumbText: (text: string) => {
    const element = document.querySelector(`text="${text}"`);
    expect(element).toBeInTheDocument();
    return element;
  },

  expectHomeLink: () => {
    const homeLink = document.querySelector('[aria-label="Go to home page"]');
    expect(homeLink).toBeInTheDocument();
    expect(homeLink).toHaveAttribute('href', '/');
    return homeLink;
  },

  expectNoNavigation: () => {
    const nav = document.querySelector('[role="navigation"]');
    expect(nav).not.toBeInTheDocument();
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
  createMockContact: (
    overrides: Partial<ContactResource> = {}
  ): ContactResource => {
    const baseContact: ContactResource = {
      id: '1',
      type: 'contacts' as const,
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
            type: 'contact_methods' as const,
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
        relationships: [],
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
    } as ContactResource;
  },

  createMockContactsResponse: (
    contacts: ContactResource[] = [],
    total?: number
  ): ContactListResponse => ({
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

  createEmptyContactsResponse: (): ContactListResponse => ({
    data: [],
    meta: {
      total: 0,
      page: 1,
      per_page: 20,
      total_pages: 0,
    },
  }),

  createMockContactResponse: (contact?: ContactResource) => ({
    data:
      contact ||
      contactTestUtils.createMockContact({
        attributes: {
          first_name: 'John',
          last_name: 'Doe',
          middle_name: 'William',
          nick_name: 'Johnny',
          created_at: '2024-01-01T00:00:00Z',
          updated_at: '2024-01-01T00:00:00Z',
          contact_methods: [],
          addresses: [],
          notes: [],
          relationships: [],
        },
      }),
  }),
} as const;

export function createMockGetContactPaginationMeta(
  meta?: Record<string, unknown>
) {
  return {
    totalCount:
      typeof meta?.total_count === 'number'
        ? meta.total_count
        : typeof meta?.total === 'number'
          ? meta.total
          : undefined,
    currentPage:
      typeof meta?.current_page === 'number'
        ? meta.current_page
        : typeof meta?.page === 'number'
          ? meta.page
          : undefined,
    pageCount:
      typeof meta?.page_count === 'number'
        ? meta.page_count
        : typeof meta?.total_pages === 'number'
          ? meta.total_pages
          : typeof meta?.totalPages === 'number'
            ? meta.totalPages
            : undefined,
    perPage:
      typeof meta?.per_page === 'number'
        ? meta.per_page
        : typeof meta?.limit === 'number'
          ? meta.limit
          : undefined,
  };
}

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

// HomePage-specific test utilities
export const homePageTestUtils = {
  // Feature cards data for consistent testing
  FEATURE_CARDS: [
    {
      title: 'Contacts',
      description:
        'Manage your personal and professional contacts with tags and Google sync.',
    },
    {
      title: 'Journal',
      description:
        'Keep track of your thoughts, experiences, and memories with mood tracking.',
    },
    {
      title: 'Calendar',
      description:
        'Sync with Google Calendar and link events to photos and journal entries.',
    },
    {
      title: 'Photos',
      description:
        'Connect with Immich to link photos to contacts, events, and journal entries.',
    },
    {
      title: 'AI Integration',
      description:
        'MCP protocol support for AI assistants to access and manage your data.',
    },
    {
      title: 'System Status',
      description: 'Monitor system health and integration status.',
    },
  ] as const,

  // Mock authenticated session response
  createAuthenticatedSessionMock: () => ({
    ok: true,
    json: async () => ({
      authenticated: true,
      user: {
        id: '1',
        email: 'test@example.com',
        name: 'Test User',
      },
    }),
  }),

  // Setup common HomePage test environment
  setupHomePageTest: () => {
    setupMocks.clearMocks();
    setupMocks.fetch();

    // Mock authenticated session
    (fetch as jest.Mock).mockResolvedValue(
      homePageTestUtils.createAuthenticatedSessionMock()
    );
  },
} as const;

// Re-export testing library utilities
export * from '@testing-library/react';
export { userEvent } from '@testing-library/user-event';
