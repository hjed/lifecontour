// Mock constants for testing
export const API_ENDPOINTS = {
  AUTH: {
    LOGIN: '/api/auth/login',
    LOGOUT: '/api/auth/logout',
    SESSION: '/api/auth/session',
    CALLBACK: '/api/auth/callback',
  },
  CONTACTS: {
    BASE: '/api/contacts',
    SEARCH: '/api/contacts/search',
  },
  SEARCH: {
    CONTACTS: '/api/search/contacts',
    GLOBAL: '/api/search/global',
    SUGGESTIONS: '/api/search/suggestions',
  },
};

export const HTTP_HEADERS = {
  CONTENT_TYPE: 'Content-Type',
  APPLICATION_JSON: 'application/json',
  AUTHORIZATION: 'Authorization',
};

export const ERROR_MESSAGES = {
  LOGIN_FAILED: 'Login failed',
  LOGOUT_FAILED: 'Logout failed',
  AUTH_FAILED: 'Authentication failed',
  SESSION_EXPIRED: 'Your session has expired. Please sign in again.',
  OAUTH_ERROR: 'OAuth error',
  MISSING_OAUTH_PARAMS: 'Missing required OAuth parameters',
  NETWORK_ERROR: 'Network error occurred',
  UNKNOWN_ERROR: 'An unknown error occurred',
  FETCH_FAILED: 'Failed to fetch data. Please try again.',
};

export const SUCCESS_MESSAGES = {
  SIGNED_IN: 'Successfully signed in',
  SIGNED_OUT: 'Successfully signed out',
  CONTACT_CREATED: 'Contact created successfully',
  CONTACT_UPDATED: 'Contact updated successfully',
  CONTACT_DELETED: 'Contact deleted successfully',
};
