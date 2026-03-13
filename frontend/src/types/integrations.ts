/**
 * TypeScript types for integration API responses and data structures.
 *
 * Defines types for Google Contacts integration, sync jobs, and health monitoring.
 */

import type { ReactNode } from 'react';

// Base integration types
export type SyncType = 'smart' | 'full';
export type SyncStatus =
  | 'queued'
  | 'running'
  | 'completed'
  | 'failed'
  | 'cancelled';
export type IntegrationStatus =
  | 'active'
  | 'inactive'
  | 'error'
  | 'disconnected';
export type HealthStatus = 'healthy' | 'degraded' | 'unhealthy';

// Google Contacts Integration Status
export interface GoogleStatusAttributes {
  connected: boolean;
  lastSync: string | null;
  syncCount: number;
  status: IntegrationStatus;
  errorMessage?: string;
}

export interface GoogleStatusResponse {
  data: {
    id: string;
    type: 'integration-status';
    attributes: GoogleStatusAttributes;
  };
}

// Sync Job Types
export interface SyncJobAttributes {
  status: SyncStatus;
  syncType: SyncType;
  createdAt: string;
  startedAt?: string;
  completedAt?: string;
  errorMessage?: string;
  contactsProcessed?: number;
  contactsCreated?: number;
  contactsUpdated?: number;
  contactsDeleted?: number;
  progress?: number; // 0-100 percentage
}

export interface SyncJobResponse {
  data: {
    id: string;
    type: 'sync-job';
    attributes: SyncJobAttributes;
  };
}

// Sync Job List Response
export interface SyncJobListResponse {
  data: Array<{
    id: string;
    type: 'sync-job';
    attributes: SyncJobAttributes;
  }>;
  meta: {
    total: number;
    page: number;
    pageSize: number;
  };
}

// Integration Health Types
export interface ComponentHealth {
  status: HealthStatus;
  latency?: number;
  lastSeen?: string;
  errorMessage?: string;
}

export interface IntegrationHealthAttributes {
  redis: ComponentHealth;
  worker: ComponentHealth;
  overall: HealthStatus;
  lastChecked: string;
}

export interface IntegrationHealthResponse {
  data: {
    id: string;
    type: 'integration-health';
    attributes: IntegrationHealthAttributes;
  };
}

// Sync Trigger Request
export interface SyncTriggerRequest {
  sync_type: SyncType;
}

// Integration UI State Types
export interface IntegrationUIState {
  isConnected: boolean;
  lastSyncJob: SyncJobAttributes | null;
  currentJob: SyncJobAttributes | null;
  health: IntegrationHealthAttributes | null;
  recentJobs: SyncJobAttributes[];
}

// Integration Settings Types
export interface GoogleSettings {
  autoSync: boolean;
  syncInterval: number; // minutes
  syncOnStartup: boolean;
  conflictResolution: 'local' | 'remote' | 'manual';
}

export interface IntegrationSettings {
  googleContacts: GoogleSettings;
}

// Error Types
export interface IntegrationError {
  code: string;
  message: string;
  details?: Record<string, unknown>;
  timestamp: string;
}

// OAuth Types
export interface OAuthAuthorizeRequest {
  redirect_url?: string;
}

export interface OAuthAuthorizeResponse {
  authorization_url: string;
  state: string;
}

export interface OAuthCallbackRequest {
  code: string;
  state: string;
}

export interface OAuthCallbackResponse {
  success: boolean;
  message: string;
  redirect_url: string;
}

export interface OAuthDisconnectResponse {
  success: boolean;
  message: string;
}

// Integration Statistics
export interface IntegrationStats {
  totalContacts: number;
  syncedContacts: number;
  lastSyncDuration: number; // seconds
  averageSyncDuration: number; // seconds
  successfulSyncs: number;
  failedSyncs: number;
  syncFrequency: number; // syncs per day
}

export interface IntegrationStatsResponse {
  data: {
    id: string;
    type: 'integration-stats';
    attributes: IntegrationStats;
  };
}

// Sync History Types
export interface SyncHistoryFilters {
  status?: SyncStatus;
  syncType?: SyncType;
  dateFrom?: string;
  dateTo?: string;
  limit?: number;
  offset?: number;
}

// Component Props Types
export interface IntegrationCardProps {
  title: string;
  description: string;
  status: IntegrationStatus;
  connected: boolean;
  lastSync?: string;
  onConnect?: () => void;
  onDisconnect?: () => void;
  onSync?: (syncType: SyncType) => void;
  children?: ReactNode;
}

export interface SyncJobCardProps {
  job: SyncJobAttributes;
  showDetails?: boolean;
  onCancel?: () => void;
  onRetry?: () => void;
}

export interface HealthIndicatorProps {
  health: IntegrationHealthAttributes;
  showDetails?: boolean;
}

export interface SyncHistoryProps {
  jobs: SyncJobAttributes[];
  loading?: boolean;
  onLoadMore?: () => void;
  hasMore?: boolean;
}

// Form Types
export interface SyncTriggerFormData {
  syncType: SyncType;
  force?: boolean;
}

export interface IntegrationSettingsFormData {
  autoSync: boolean;
  syncInterval: number;
  syncOnStartup: boolean;
  conflictResolution: 'local' | 'remote' | 'manual';
}
