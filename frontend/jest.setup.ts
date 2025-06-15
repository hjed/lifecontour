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
  },
  SUCCESS_MESSAGES: {
    SIGNED_IN: 'Successfully signed in',
    SIGNED_OUT: 'Successfully signed out',
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
  // eslint-disable-next-line no-var
  var __mockRouter: {
    push: jest.Mock;
    replace: jest.Mock;
    prefetch: jest.Mock;
    back: jest.Mock;
    forward: jest.Mock;
    refresh: jest.Mock;
  };
}

global.__mockRouter = {
  push: mockPush,
  replace: mockReplace,
  prefetch: mockPrefetch,
  back: mockBack,
  forward: mockForward,
  refresh: mockRefresh,
};

// Mock window.location
Object.defineProperty(window, 'location', {
  value: {
    href: 'http://localhost:3000',
    origin: 'http://localhost:3000',
    pathname: '/',
    search: '',
    hash: '',
    assign: jest.fn(),
    replace: jest.fn(),
    reload: jest.fn(),
  },
  writable: true,
});
