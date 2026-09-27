/**
 * Application constants to avoid string duplication.
 *
 * Centralizes all string literals and configuration values
 * to meet SonarQube quality standards.
 */

// Product identity: the single source of the product name in the frontend
export const APP_NAME = 'Lifecontour';
export const APP_TAGLINE = 'Your journal, people and adventures — self-hosted.';

// API Endpoints
export const API_ENDPOINTS = {
  AUTH: {
    LOGIN: '/api/auth/login',
    CALLBACK: '/api/auth/callback',
    LOGOUT: '/api/auth/logout',
    SESSION: '/api/auth/status',
    REFRESH: '/api/auth/refresh',
    PROVIDERS: '/api/auth/providers',
  },
  CONTACTS: {
    BASE: '/api/contacts',
    BY_ID: (id: string) => `/api/contacts/${id}`,
  },
  JOURNALS: {
    BASE: '/api/journals',
    BY_ID: (id: string) => `/api/journals/${id}`,
    SEARCH: '/api/journals/search',
    EXPORT_OUTDOOR_LOGBOOK: '/api/journals/export/outdoor-logbook',
    INCOMPLETE_OUTDOOR_ACTIVITIES:
      '/api/journals/incomplete-outdoor-activities',
    INCOMPLETE_OUTDOOR_ACTIVITY_DISMISS: (journalId: string) =>
      `/api/journals/incomplete-outdoor-activities/${journalId}/dismiss`,
    INCOMPLETE_OUTDOOR_ACTIVITY_UNDISMISS: (journalId: string) =>
      `/api/journals/incomplete-outdoor-activities/${journalId}/undismiss`,
    OUTDOOR_DASHBOARD: '/api/journals/outdoor-dashboard',
  },
  // The home dashboard is a top-level singleton, not a journal-scoped
  // projection like the outdoor one: it reads across journals, tasks,
  // contacts and the summary, so it does not hang off /api/journals.
  HOME_DASHBOARD: '/api/home-dashboard',
  // Tasks hang off a journal path to create and list, but are reached by their
  // own id for everything else — there is deliberately no task collection.
  TASKS: {
    BY_ID: (id: string) => `/api/tasks/${id}`,
    FOR_JOURNAL: (journalId: string) => `/api/journals/${journalId}/tasks`,
    RETARGET: (id: string) => `/api/tasks/${id}/retarget`,
    CONTACTS: (id: string) => `/api/tasks/${id}/relationships/contacts`,
    CONTACT: (id: string, contactId: string) =>
      `/api/tasks/${id}/relationships/contacts/${contactId}`,
    INTERMEDIATE_JOURNALS: (id: string) =>
      `/api/tasks/${id}/relationships/intermediate-journals`,
    INTERMEDIATE_JOURNAL: (id: string, journalId: string) =>
      `/api/tasks/${id}/relationships/intermediate-journals/${journalId}`,
    HISTORY: (id: string) => `/api/tasks/${id}/history`,
  },
  TEMPLATES: {
    BASE: '/api/templates',
    BY_ID: (id: string) => `/api/templates/${id}`,
  },
  ROUTES: {
    BASE: '/api/routes',
    BY_ID: (id: string) => `/api/routes/${id}`,
  },
  SEARCH: {
    CONTACTS: '/api/search/contacts',
    GLOBAL: '/api/search/global',
    SUGGESTIONS: '/api/search/suggestions',
  },
} as const;

// HTTP Headers
export const HTTP_HEADERS = {
  CONTENT_TYPE: 'Content-Type',
  APPLICATION_JSON: 'application/json',
} as const;

// HTTP Methods
export const HTTP_METHODS = {
  GET: 'GET',
  POST: 'POST',
  PUT: 'PUT',
  PATCH: 'PATCH',
  DELETE: 'DELETE',
} as const;

// Authentication Storage Keys
export const AUTH_STORAGE_KEYS = {
  USER: 'auth_user',
  TOKEN: 'auth_token',
  REFRESH_TOKEN: 'auth_refresh_token',
  EXPIRES_AT: 'auth_expires_at',
  PROVIDER: 'auth_provider',
} as const;

// OAuth Provider Names
export const OAUTH_PROVIDER_NAMES = {
  GITHUB: 'GitHub',
  MICROSOFT: 'Microsoft',
  DISCORD: 'Discord',
  GENERIC: 'OAuth2',
} as const;

// OAuth Provider Colors
export const OAUTH_PROVIDER_COLORS = {
  GITHUB: '#24292e',
  MICROSOFT: '#0078d4',
  DISCORD: '#5865f2',
  GENERIC: '#6b7280',
} as const;

// OAuth Provider Icons
export const OAUTH_PROVIDER_ICONS = {
  GITHUB: 'github',
  MICROSOFT: 'microsoft',
  DISCORD: 'discord',
  GENERIC: 'key',
} as const;

// Predefined Tag Colors (Australian theme)
export const TAG_COLORS = [
  '#E53E3E', // Red
  '#DD6B20', // Orange
  '#D69E2E', // Yellow
  '#38A169', // Green
  '#319795', // Teal
  '#3182CE', // Blue
  '#805AD5', // Purple
  '#D53F8C', // Pink
  '#718096', // Gray
  '#2D3748', // Dark Gray
] as const;

// Search Sort Options
export const SEARCH_SORT_OPTIONS = [
  { value: 'relevance', label: 'Relevance' },
  { value: 'created_at:desc', label: 'Newest First' },
  { value: 'created_at:asc', label: 'Oldest First' },
  { value: 'updated_at:desc', label: 'Recently Updated' },
  { value: 'name:asc', label: 'Name A-Z' },
  { value: 'name:desc', label: 'Name Z-A' },
] as const;

// Entity Types for Global Search
export const ENTITY_TYPES = [
  'contacts',
  'journal_entries',
  'calendar_events',
  'albums',
] as const;

// Common UI Text
export const UI_TEXT = {
  WELCOME_BACK: 'Welcome Back',
  SIGN_IN_DESCRIPTION: `Sign in to ${APP_NAME}`,
  CONTINUE_WITH: 'Continue with',
  CONNECTING_TO: 'Connecting to',
  PRIVACY_NOTICE:
    'By signing in, you agree to our terms of service and privacy policy.',
  SELF_HOSTED_NOTICE: `This is a private, self-hosted ${APP_NAME} instance.`,
  LOADING: 'Loading',
  CHECKING_AUTH: 'Checking your authentication status',
  PLEASE_WAIT: 'Please wait...',
  COMPLETING_SIGN_IN: 'Completing Sign In',
  FINISH_SESSION_SETUP: 'Please wait while we finish setting up your session',
  SHOULD_TAKE_MOMENT: 'This should only take a moment...',
  AUTH_FAILED: 'Authentication Failed',
  PROBLEM_SIGNING_IN: 'There was a problem signing you in',
  TRY_AGAIN: 'Try signing in again',
} as const;

// Error Messages
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
  CREATE_FAILED: 'Failed to create item. Please try again.',
  UPDATE_FAILED: 'Failed to update item. Please try again.',
  DELETE_FAILED: 'Failed to delete item. Please try again.',
  SEARCH_FAILED: 'Search failed. Please try again.',
} as const;

// Success Messages
export const SUCCESS_MESSAGES = {
  SIGNED_OUT: 'Signed out successfully',
  SIGNED_IN: 'Signed in successfully',
  PROFILE_UPDATED: 'Profile updated successfully',
  SETTINGS_SAVED: 'Settings saved successfully',
  CONTACT_CREATED: 'Contact created successfully',
  CONTACT_UPDATED: 'Contact updated successfully',
  CONTACT_DELETED: 'Contact deleted successfully',
  JOURNAL_CREATED: 'Journal created successfully',
  JOURNAL_UPDATED: 'Journal updated successfully',
  JOURNAL_DELETED: 'Journal deleted successfully',
  TAG_ASSIGNED: 'Tag assigned successfully',
  TAG_REMOVED: 'Tag removed successfully',
  TAG_CREATED: 'Tag created successfully',
  TAG_UPDATED: 'Tag updated successfully',
  TAG_DELETED: 'Tag deleted successfully',
  TASK_CREATED: 'Task created successfully',
  TASK_UPDATED: 'Task updated successfully',
  TASK_DELETED: 'Task deleted successfully',
  TASK_RETARGETED: 'Task moved to its new due journal',
  TASK_CONTACT_LINKED: 'Contact linked successfully',
  TASK_CONTACT_UNLINKED: 'Contact unlinked successfully',
  TASK_JOURNAL_ATTACHED: 'Journal linked successfully',
  TASK_JOURNAL_DETACHED: 'Journal unlinked successfully',
  CREATE_SUCCESS: 'Created successfully',
  UPDATE_SUCCESS: 'Updated successfully',
  DELETE_SUCCESS: 'Deleted successfully',
} as const;

// Validation Messages
export const VALIDATION_MESSAGES = {
  REQUIRED_FIELD: 'This field is required',
  INVALID_EMAIL: 'Please enter a valid email address',
  INVALID_PHONE: 'Please enter a valid phone number',
  INVALID_URL: 'Please enter a valid URL',
  MIN_LENGTH: (min: number) => `Must be at least ${min} characters`,
  MAX_LENGTH: (max: number) => `Must be no more than ${max} characters`,
} as const;

// Date Formats (Australian)
export const DATE_FORMATS = {
  SHORT: 'dd/MM/yyyy',
  LONG: 'dd MMMM yyyy',
  WITH_TIME: 'dd/MM/yyyy HH:mm',
  TIME_ONLY: 'HH:mm',
  ISO: 'yyyy-MM-dd',
} as const;

// Pagination
export const PAGINATION = {
  DEFAULT_PAGE_SIZE: 20,
  MAX_PAGE_SIZE: 100,
  MIN_PAGE_SIZE: 5,
} as const;

// Timeouts (in milliseconds)
export const TIMEOUTS = {
  API_REQUEST: 30000, // 30 seconds
  DEBOUNCE_SEARCH: 300, // 300ms
  TOAST_DURATION: 4000, // 4 seconds
  LOADING_DELAY: 100, // 100ms
} as const;

// Local Storage Keys
export const STORAGE_KEYS = {
  THEME: 'theme',
  LANGUAGE: 'language',
  SIDEBAR_COLLAPSED: 'sidebar_collapsed',
  SEARCH_HISTORY: 'search_history',
} as const;
