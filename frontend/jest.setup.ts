import '@testing-library/jest-dom';
import type { AppRouterInstance } from 'next/dist/shared/lib/app-router-context.shared-runtime';

// Increase default timeout (5000ms) to 15000ms to prevent CI flakiness
jest.setTimeout(15000);

import { configure } from '@testing-library/react';
// Increase RTL's default async timeout from 1000ms to 5000ms to avoid CPU starvation failures in full suite runs
configure({ asyncUtilTimeout: 5000 });

// Mock ResizeObserver for Radix UI components
globalThis.ResizeObserver = jest.fn().mockImplementation(() => ({
  observe: jest.fn(),
  unobserve: jest.fn(),
  disconnect: jest.fn(),
}));

// Mock missing JSDOM functions required by Radix UI Select. Guarded because a
// few suites opt into the `node` environment (`@jest-environment node`) where
// there is no `window` — see src/app/__tests__/globals-css.test.ts.
if (typeof window !== 'undefined') {
  window.getSelection = jest.fn().mockReturnValue({
    removeAllRanges: jest.fn(),
  });
  window.HTMLElement.prototype.scrollIntoView = jest.fn();
  window.HTMLElement.prototype.hasPointerCapture = jest.fn();
  window.HTMLElement.prototype.releasePointerCapture = jest.fn();
}

// Empty replacing pointer event block

// Create a mock router with proper typing
const mockPush = jest.fn();
const mockReplace = jest.fn();
const mockPrefetch = jest.fn();
const mockBack = jest.fn();
const mockForward = jest.fn();
const mockRefresh = jest.fn();

const mockRouter: Partial<AppRouterInstance> = {
  push: mockPush,
  replace: mockReplace,
  prefetch: mockPrefetch,
  back: mockBack,
  forward: mockForward,
  refresh: mockRefresh,
};

// Mock Next.js router with proper types - using doMock to ensure it runs after Next.js setup
jest.doMock('next/navigation', () => ({
  useRouter: jest.fn(() => mockRouter),
  usePathname: jest.fn(() => '/'),
  useSearchParams: jest.fn(() => new URLSearchParams()),
  useParams: jest.fn(() => ({})),
}));

// Mock constants to ensure they're available in tests
jest.mock('@/lib/constants', () => ({
  API_ENDPOINTS: {
    AUTH: {
      LOGIN: '/api/auth/login',
      LOGOUT: '/api/auth/logout',
      SESSION: '/api/auth/session',
      CALLBACK: '/api/auth/callback',
      PROVIDERS: '/api/auth/providers',
    },
    CONTACTS: {
      BASE: '/api/contacts',
    },
    SEARCH: {
      CONTACTS: '/api/search/contacts',
      GLOBAL: '/api/search/global',
      SUGGESTIONS: '/api/search/suggestions',
    },
  },
  HTTP_HEADERS: {
    CONTENT_TYPE: 'Content-Type',
    APPLICATION_JSON: 'application/json',
    AUTHORIZATION: 'Authorization',
  },
  TIMEOUTS: {
    API_REQUEST: 30000,
    DEBOUNCE_SEARCH: 300,
    TOAST_DURATION: 4000,
    LOADING_DELAY: 100,
  },
  VALIDATION_MESSAGES: {
    REQUIRED_FIELD: 'This field is required',
    INVALID_EMAIL: 'Please enter a valid email address',
    INVALID_PHONE: 'Please enter a valid phone number',
    INVALID_URL: 'Please enter a valid URL',
    MIN_LENGTH: (min: number) => `Must be at least ${min} characters`,
    MAX_LENGTH: (max: number) => `Must be no more than ${max} characters`,
  },
  DATE_FORMATS: {
    SHORT: 'dd/MM/yyyy',
    LONG: 'dd MMMM yyyy',
    WITH_TIME: 'dd/MM/yyyy HH:mm',
    TIME_ONLY: 'HH:mm',
    ISO: 'yyyy-MM-dd',
  },
  ERROR_MESSAGES: {
    LOGIN_FAILED: 'Login failed',
    LOGOUT_FAILED: 'Logout failed',
    AUTH_FAILED: 'Authentication failed',
    SESSION_EXPIRED: 'Your session has expired. Please sign in again.',
    OAUTH_ERROR: 'OAuth error',
    MISSING_OAUTH_PARAMS: 'Missing required OAuth parameters',
    NETWORK_ERROR: 'Network error occurred',
    UNKNOWN_ERROR: 'An unknown error occurred',
    FETCH_FAILED: 'Failed to fetch data. Please try again.',
    CREATE_FAILED: 'Failed to create item. Please try again.',
    UPDATE_FAILED: 'Failed to update item. Please try again.',
    DELETE_FAILED: 'Failed to delete item. Please try again.',
    SEARCH_FAILED: 'Search failed. Please try again.',
  },
  SUCCESS_MESSAGES: {
    SIGNED_IN: 'Successfully signed in',
    SIGNED_OUT: 'Successfully signed out',
    PROFILE_UPDATED: 'Profile updated successfully',
    SETTINGS_SAVED: 'Settings saved successfully',
    CONTACT_CREATED: 'Contact created successfully',
    CONTACT_UPDATED: 'Contact updated successfully',
    CONTACT_DELETED: 'Contact deleted successfully',
    TAG_ASSIGNED: 'Tag assigned successfully',
    TAG_REMOVED: 'Tag removed successfully',
    TAG_CREATED: 'Tag created successfully',
  },
  TAG_COLORS: [
    '#E53E3E',
    '#DD6B20',
    '#D69E2E',
    '#38A169',
    '#319795',
    '#3182CE',
    '#805AD5',
    '#D53F8C',
    '#718096',
    '#2D3748',
  ],
  OAUTH_PROVIDER_NAMES: {
    GITHUB: 'GitHub',
    MICROSOFT: 'Microsoft',
    DISCORD: 'Discord',
    GENERIC: 'Generic',
  },
  OAUTH_PROVIDER_ICONS: {
    GITHUB: 'github',
    MICROSOFT: 'microsoft',
    DISCORD: 'discord',
    GENERIC: 'generic',
  },
  OAUTH_PROVIDER_COLORS: {
    GITHUB: '#333',
    MICROSOFT: '#0078d4',
    DISCORD: '#5865f2',
    GENERIC: '#666',
  },
  AUTH_STORAGE_KEYS: {
    SESSION: 'auth_session',
    CSRF_TOKEN: 'csrf_token',
  },
  // Product naming and UI copy come from the real module so they cannot drift
  APP_NAME:
    jest.requireActual<typeof import('@/lib/constants')>('@/lib/constants')
      .APP_NAME,
  APP_TAGLINE:
    jest.requireActual<typeof import('@/lib/constants')>('@/lib/constants')
      .APP_TAGLINE,
  UI_TEXT:
    jest.requireActual<typeof import('@/lib/constants')>('@/lib/constants')
      .UI_TEXT,
  SOURCE_CODE_URL:
    jest.requireActual<typeof import('@/lib/constants')>('@/lib/constants')
      .SOURCE_CODE_URL,
  THIRD_PARTY_NOTICES_PATH:
    jest.requireActual<typeof import('@/lib/constants')>('@/lib/constants')
      .THIRD_PARTY_NOTICES_PATH,
  PROJECT_LINKS:
    jest.requireActual<typeof import('@/lib/constants')>('@/lib/constants')
      .PROJECT_LINKS,
}));

// Export mock functions for test access
declare global {
  var __mockRouter: {
    push: jest.Mock;
    replace: jest.Mock;
    prefetch: jest.Mock;
    back: jest.Mock;
    forward: jest.Mock;
    refresh: jest.Mock;
  };
}

globalThis.__mockRouter = {
  push: mockPush,
  replace: mockReplace,
  prefetch: mockPrefetch,
  back: mockBack,
  forward: mockForward,
  refresh: mockRefresh,
};

// Note: window.location cannot be mocked globally in Jest 30+ with jsdom
// due to JSDOM v21+ making it non-configurable.
// If individual tests need to mock window.location methods, use:
// jest.spyOn(window.location, 'assign').mockImplementation(() => {});
// Or use JSDOM's reconfigure method if you need to change the URL.
