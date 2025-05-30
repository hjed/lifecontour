import type { ErrorCode, HttpStatus } from '../constants/index.js';
import { ERROR_CODES, HTTP_STATUS } from '../constants/index.js';

// Base application error class
export abstract class AppError extends Error {
  abstract readonly code: ErrorCode;
  abstract readonly statusCode: HttpStatus;
  readonly timestamp: Date;
  readonly details: Record<string, unknown>;

  constructor(message: string, details: Record<string, unknown> = {}) {
    super(message);
    this.name = this.constructor.name;
    this.timestamp = new Date();
    this.details = details;

    // Maintains proper stack trace for where our error was thrown (only available on V8)
    if (Error.captureStackTrace) {
      Error.captureStackTrace(this, this.constructor);
    }
  }

  toJSON() {
    return {
      name: this.name,
      message: this.message,
      code: this.code,
      statusCode: this.statusCode,
      timestamp: this.timestamp,
      details: this.details,
      stack: this.stack,
    };
  }
}

// Validation errors (400)
export class ValidationError extends AppError {
  readonly code = ERROR_CODES.VALIDATION_ERROR;
  readonly statusCode = HTTP_STATUS.BAD_REQUEST;

  constructor(message: string, field?: string, value?: unknown) {
    super(message, { field, value });
  }
}

export class InvalidInputError extends AppError {
  readonly code = ERROR_CODES.INVALID_INPUT;
  readonly statusCode = HTTP_STATUS.BAD_REQUEST;
}

export class MissingRequiredFieldError extends AppError {
  readonly code = ERROR_CODES.MISSING_REQUIRED_FIELD;
  readonly statusCode = HTTP_STATUS.BAD_REQUEST;

  constructor(field: string) {
    super(`Required field '${field}' is missing`, { field });
  }
}

// Authentication errors (401)
export class UnauthorizedError extends AppError {
  readonly code = ERROR_CODES.UNAUTHORIZED;
  readonly statusCode = HTTP_STATUS.UNAUTHORIZED;

  constructor(message = 'Authentication required') {
    super(message);
  }
}

export class InvalidTokenError extends AppError {
  readonly code = ERROR_CODES.INVALID_TOKEN;
  readonly statusCode = HTTP_STATUS.UNAUTHORIZED;

  constructor(message = 'Invalid or malformed token') {
    super(message);
  }
}

export class TokenExpiredError extends AppError {
  readonly code = ERROR_CODES.TOKEN_EXPIRED;
  readonly statusCode = HTTP_STATUS.UNAUTHORIZED;

  constructor(message = 'Token has expired') {
    super(message);
  }
}

// Authorization errors (403)
export class ForbiddenError extends AppError {
  readonly code = ERROR_CODES.FORBIDDEN;
  readonly statusCode = HTTP_STATUS.FORBIDDEN;

  constructor(message = 'Access denied') {
    super(message);
  }
}

export class InsufficientPermissionsError extends AppError {
  readonly code = ERROR_CODES.INSUFFICIENT_PERMISSIONS;
  readonly statusCode = HTTP_STATUS.FORBIDDEN;

  constructor(permission: string) {
    super(`Insufficient permissions: ${permission}`, { permission });
  }
}

// Not found errors (404)
export class NotFoundError extends AppError {
  readonly code = ERROR_CODES.NOT_FOUND;
  readonly statusCode = HTTP_STATUS.NOT_FOUND;

  constructor(message = 'Resource not found') {
    super(message);
  }
}

export class ResourceNotFoundError extends AppError {
  readonly code = ERROR_CODES.RESOURCE_NOT_FOUND;
  readonly statusCode = HTTP_STATUS.NOT_FOUND;

  constructor(resource: string, id: string) {
    super(`${resource} with id '${id}' not found`, { resource, id });
  }
}

// Conflict errors (409)
export class ConflictError extends AppError {
  readonly code = ERROR_CODES.CONFLICT;
  readonly statusCode = HTTP_STATUS.CONFLICT;

  constructor(message = 'Resource conflict') {
    super(message);
  }
}

export class DuplicateResourceError extends AppError {
  readonly code = ERROR_CODES.DUPLICATE_RESOURCE;
  readonly statusCode = HTTP_STATUS.CONFLICT;

  constructor(resource: string, field: string, value: string) {
    super(`${resource} with ${field} '${value}' already exists`, { resource, field, value });
  }
}

// Rate limiting errors (429)
export class RateLimitExceededError extends AppError {
  readonly code = ERROR_CODES.RATE_LIMIT_EXCEEDED;
  readonly statusCode = HTTP_STATUS.TOO_MANY_REQUESTS;

  constructor(limit: number, windowMs: number) {
    super(`Rate limit exceeded: ${limit} requests per ${windowMs}ms`, { limit, windowMs });
  }
}

// Server errors (500)
export class InternalError extends AppError {
  readonly code = ERROR_CODES.INTERNAL_ERROR;
  readonly statusCode = HTTP_STATUS.INTERNAL_SERVER_ERROR;

  constructor(message = 'Internal server error', cause?: Error) {
    super(message, { cause: cause?.message, stack: cause?.stack });
  }
}

export class DatabaseError extends AppError {
  readonly code = ERROR_CODES.DATABASE_ERROR;
  readonly statusCode = HTTP_STATUS.INTERNAL_SERVER_ERROR;

  constructor(message: string, operation?: string, cause?: Error) {
    super(`Database error: ${message}`, { operation, cause: cause?.message });
  }
}

export class ExternalServiceError extends AppError {
  readonly code = ERROR_CODES.EXTERNAL_SERVICE_ERROR;
  readonly statusCode = HTTP_STATUS.BAD_GATEWAY;

  constructor(service: string, message: string, statusCode?: number) {
    super(`External service error (${service}): ${message}`, {
      service,
      externalStatusCode: statusCode,
    });
  }
}

// Integration-specific errors
export class GoogleApiError extends AppError {
  readonly code = ERROR_CODES.GOOGLE_API_ERROR;
  readonly statusCode = HTTP_STATUS.BAD_GATEWAY;

  constructor(message: string, apiMethod?: string, statusCode?: number) {
    super(`Google API error: ${message}`, { apiMethod, externalStatusCode: statusCode });
  }
}

export class ImmichApiError extends AppError {
  readonly code = ERROR_CODES.IMMICH_API_ERROR;
  readonly statusCode = HTTP_STATUS.BAD_GATEWAY;

  constructor(message: string, endpoint?: string, statusCode?: number) {
    super(`Immich API error: ${message}`, { endpoint, externalStatusCode: statusCode });
  }
}

// Error factory functions
export const createValidationError = (
  field: string,
  message: string,
  value?: unknown
): ValidationError => {
  return new ValidationError(`Validation failed for field '${field}': ${message}`, field, value);
};

export const createNotFoundError = (resource: string, id: string): ResourceNotFoundError => {
  return new ResourceNotFoundError(resource, id);
};

export const createDuplicateError = (
  resource: string,
  field: string,
  value: string
): DuplicateResourceError => {
  return new DuplicateResourceError(resource, field, value);
};

export const createDatabaseError = (operation: string, cause: Error): DatabaseError => {
  return new DatabaseError(`Failed to ${operation}`, operation, cause);
};

// Error type guards
export const isAppError = (error: unknown): error is AppError => {
  return error instanceof AppError;
};

export const isValidationError = (error: unknown): error is ValidationError => {
  return error instanceof ValidationError;
};

export const isNotFoundError = (error: unknown): error is NotFoundError => {
  return error instanceof NotFoundError || error instanceof ResourceNotFoundError;
};

export const isUnauthorizedError = (error: unknown): error is UnauthorizedError => {
  return (
    error instanceof UnauthorizedError ||
    error instanceof InvalidTokenError ||
    error instanceof TokenExpiredError
  );
};

export const isForbiddenError = (error: unknown): error is ForbiddenError => {
  return error instanceof ForbiddenError || error instanceof InsufficientPermissionsError;
};

export const isConflictError = (error: unknown): error is ConflictError => {
  return error instanceof ConflictError || error instanceof DuplicateResourceError;
};

export const isServerError = (error: unknown): error is InternalError => {
  return (
    error instanceof InternalError ||
    error instanceof DatabaseError ||
    error instanceof ExternalServiceError
  );
};

// Error handling utilities
export const getErrorStatusCode = (error: unknown): HttpStatus => {
  if (isAppError(error)) {
    return error.statusCode;
  }
  return HTTP_STATUS.INTERNAL_SERVER_ERROR;
};

export const getErrorCode = (error: unknown): ErrorCode => {
  if (isAppError(error)) {
    return error.code;
  }
  return ERROR_CODES.INTERNAL_ERROR;
};

export const formatErrorForLogging = (error: unknown): Record<string, unknown> => {
  if (isAppError(error)) {
    return {
      name: error.name,
      message: error.message,
      code: error.code,
      statusCode: error.statusCode,
      timestamp: error.timestamp,
      details: error.details,
      stack: error.stack,
    };
  }

  if (error instanceof Error) {
    return {
      name: error.name,
      message: error.message,
      stack: error.stack,
    };
  }

  return {
    error: String(error),
  };
};
