// Common types used across the application

// Base entity interface
export interface BaseEntity {
  id: string;
  createdAt: Date;
  updatedAt: Date;
}

// API Response types following JSON API specification
export interface JsonApiResponse<T = unknown> {
  data: T;
  meta?: {
    total?: number;
    page?: number;
    pageSize?: number;
    hasNext?: boolean;
    hasPrevious?: boolean;
  };
  links?: {
    self?: string;
    first?: string;
    last?: string;
    next?: string;
    previous?: string;
  };
}

export interface JsonApiError {
  id?: string;
  status: string;
  code?: string;
  title: string;
  detail?: string;
  source?: {
    pointer?: string;
    parameter?: string;
  };
  meta?: Record<string, unknown>;
}

export interface JsonApiErrorResponse {
  errors: JsonApiError[];
}

// Result pattern for error handling
export interface Success<T> {
  success: true;
  data: T;
}

export interface Failure {
  success: false;
  error: string;
  code: string;
  details: Record<string, unknown>;
}

export type Result<T> = Success<T> | Failure;

// Pagination types
export interface PaginationParams {
  page?: number;
  pageSize?: number;
  cursor?: string;
}

export interface PaginationMeta {
  total: number;
  page: number;
  pageSize: number;
  totalPages: number;
  hasNext: boolean;
  hasPrevious: boolean;
}

// Search and filter types
export interface SearchParams {
  query?: string;
  filters?: Record<string, unknown>;
  sort?: string;
  order?: 'asc' | 'desc';
}

// Australian locale types
export interface AustralianLocale {
  dateFormat: 'DD/MM/YYYY';
  timeFormat: '24h' | '12h';
  currency: 'AUD';
  locale: 'en-AU';
}

// Domain event types
export interface DomainEvent {
  id: string;
  type: string;
  aggregateId: string;
  aggregateType: string;
  version: number;
  occurredAt: Date;
  data: Record<string, unknown>;
  metadata?: Record<string, unknown>;
}

// Configuration types
export interface DatabaseConfig {
  filename: string;
  busyTimeout: number;
}

export interface ServerConfig {
  port: number;
  host: string;
  trustProxy: boolean;
  cors: {
    origin: string | string[];
    credentials: boolean;
  };
}

export interface LoggingConfig {
  level: 'error' | 'warn' | 'info' | 'debug';
  format: 'json' | 'simple';
  enableConsole: boolean;
  enableFile: boolean;
  filename?: string;
}

// MCP types
export interface McpToolDefinition {
  name: string;
  description: string;
  inputSchema: Record<string, unknown>;
}

export interface McpToolResult {
  content: {
    type: 'text' | 'image' | 'resource';
    text?: string;
    data?: string;
    mimeType?: string;
  }[];
  isError?: boolean;
}
