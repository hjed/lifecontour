// Application constants

// Australian locale constants
export const AUSTRALIAN_LOCALE = {
  LOCALE_CODE: 'en-AU',
  DATE_FORMAT: 'DD/MM/YYYY',
  DATE_TIME_FORMAT: 'DD/MM/YYYY HH:mm',
  TIME_FORMAT: 'HH:mm',
  CURRENCY: 'AUD',
  TIMEZONE: 'Australia/Sydney',
} as const;

// API constants
export const API_CONSTANTS = {
  DEFAULT_PAGE_SIZE: 20,
  MAX_PAGE_SIZE: 100,
  DEFAULT_TIMEOUT: 30000, // 30 seconds
  MAX_RETRY_ATTEMPTS: 3,
  RETRY_DELAY: 1000, // 1 second
} as const;

// Database constants
export const DATABASE_CONSTANTS = {
  DEFAULT_BUSY_TIMEOUT: 5000, // 5 seconds
  WAL_MODE: 'WAL',
  FOREIGN_KEYS: 'ON',
  JOURNAL_MODE: 'WAL',
  SYNCHRONOUS: 'NORMAL',
} as const;

// File upload constants
export const FILE_CONSTANTS = {
  MAX_FILE_SIZE: 10 * 1024 * 1024, // 10MB
  ALLOWED_IMAGE_TYPES: ['image/jpeg', 'image/png', 'image/gif', 'image/webp'],
  ALLOWED_DOCUMENT_TYPES: ['application/pdf', 'text/plain', 'text/csv'],
  UPLOAD_TIMEOUT: 60000, // 60 seconds
} as const;

// MCP constants
export const MCP_CONSTANTS = {
  PROTOCOL_VERSION: '2024-11-05',
  MAX_TOOL_NAME_LENGTH: 64,
  MAX_TOOL_DESCRIPTION_LENGTH: 512,
  MAX_RESULT_SIZE: 1024 * 1024, // 1MB
  DEFAULT_TIMEOUT: 30000, // 30 seconds
} as const;

// Security constants
export const SECURITY_CONSTANTS = {
  PASSWORD_MIN_LENGTH: 8,
  PASSWORD_MAX_LENGTH: 128,
  SESSION_TIMEOUT: 24 * 60 * 60 * 1000, // 24 hours
  CSRF_TOKEN_LENGTH: 32,
  API_KEY_LENGTH: 64,
  RATE_LIMIT: {
    WINDOW_MS: 15 * 60 * 1000, // 15 minutes
    MAX_REQUESTS: 100,
  },
} as const;

// Logging constants
export const LOGGING_CONSTANTS = {
  LEVELS: ['error', 'warn', 'info', 'debug'] as const,
  MAX_LOG_SIZE: 10 * 1024 * 1024, // 10MB
  MAX_LOG_FILES: 5,
  DEFAULT_FORMAT: 'json',
} as const;

// Error codes
export const ERROR_CODES = {
  // Validation errors (400x)
  VALIDATION_ERROR: 'VALIDATION_ERROR',
  INVALID_INPUT: 'INVALID_INPUT',
  MISSING_REQUIRED_FIELD: 'MISSING_REQUIRED_FIELD',

  // Authentication errors (401x)
  UNAUTHORIZED: 'UNAUTHORIZED',
  INVALID_TOKEN: 'INVALID_TOKEN',
  TOKEN_EXPIRED: 'TOKEN_EXPIRED',

  // Authorization errors (403x)
  FORBIDDEN: 'FORBIDDEN',
  INSUFFICIENT_PERMISSIONS: 'INSUFFICIENT_PERMISSIONS',

  // Not found errors (404x)
  NOT_FOUND: 'NOT_FOUND',
  RESOURCE_NOT_FOUND: 'RESOURCE_NOT_FOUND',

  // Conflict errors (409x)
  CONFLICT: 'CONFLICT',
  DUPLICATE_RESOURCE: 'DUPLICATE_RESOURCE',

  // Server errors (500x)
  INTERNAL_ERROR: 'INTERNAL_ERROR',
  DATABASE_ERROR: 'DATABASE_ERROR',
  EXTERNAL_SERVICE_ERROR: 'EXTERNAL_SERVICE_ERROR',

  // Integration errors (502x)
  GOOGLE_API_ERROR: 'GOOGLE_API_ERROR',
  IMMICH_API_ERROR: 'IMMICH_API_ERROR',

  // Rate limiting errors (429x)
  RATE_LIMIT_EXCEEDED: 'RATE_LIMIT_EXCEEDED',
} as const;

// HTTP status codes
export const HTTP_STATUS = {
  OK: 200,
  CREATED: 201,
  NO_CONTENT: 204,
  BAD_REQUEST: 400,
  UNAUTHORIZED: 401,
  FORBIDDEN: 403,
  NOT_FOUND: 404,
  CONFLICT: 409,
  UNPROCESSABLE_ENTITY: 422,
  TOO_MANY_REQUESTS: 429,
  INTERNAL_SERVER_ERROR: 500,
  BAD_GATEWAY: 502,
  SERVICE_UNAVAILABLE: 503,
} as const;

// Environment constants
export const ENVIRONMENT = {
  DEVELOPMENT: 'development',
  TEST: 'test',
  STAGING: 'staging',
  PRODUCTION: 'production',
} as const;

// Export type definitions for constants
export type LogLevel = (typeof LOGGING_CONSTANTS.LEVELS)[number];
export type Environment = (typeof ENVIRONMENT)[keyof typeof ENVIRONMENT];
export type ErrorCode = (typeof ERROR_CODES)[keyof typeof ERROR_CODES];
export type HttpStatus = (typeof HTTP_STATUS)[keyof typeof HTTP_STATUS];
