import '@testing-library/jest-dom';
import type { AppRouterInstance } from 'next/dist/shared/lib/app-router-context.shared-runtime';

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
      SEARCH: '/api/contacts/search',
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
  },
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
  UI_TEXT: {
    WELCOME_BACK: 'Welcome Back',
    SIGN_IN_DESCRIPTION: 'Sign in to your Personal Management System',
    CONTINUE_WITH: 'Continue with',
    CONNECTING_TO: 'Connecting to',
    PRIVACY_NOTICE:
      'By signing in, you agree to our terms of service and privacy policy.',
    PRIVATE_APP_NOTICE: 'This is a private application for personal use only.',
    LOADING: 'Loading',
    CHECKING_AUTH: 'Checking your authentication status',
    PLEASE_WAIT: 'Please wait...',
    COMPLETING_SIGN_IN: 'Completing Sign In',
    FINISH_SESSION_SETUP: 'Please wait while we finish setting up your session',
    SHOULD_TAKE_MOMENT: 'This should only take a moment...',
    AUTH_FAILED: 'Authentication Failed',
    PROBLEM_SIGNING_IN: 'There was a problem signing you in',
    TRY_AGAIN: 'Try signing in again',
  },
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
