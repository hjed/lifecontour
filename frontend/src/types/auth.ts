/**
 * Authentication-related types matching backend auth schemas.
 *
 * These types provide type safety for authentication flows
 * and session management.
 */

// OAuth Provider Types
export enum OAuthProvider {
  GITHUB = 'github',
  MICROSOFT = 'microsoft',
  DISCORD = 'discord',
  GENERIC = 'generic',
}

// User Session Types
export interface SessionUser {
  id: string;
  email: string;
  name: string;
  avatar_url?: string;
  provider: OAuthProvider;
  provider_id: string;
  created_at: string;
  last_login: string;
}

// Authentication State Types
export interface AuthState {
  user: SessionUser | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  error?: string;
}

// OAuth Configuration Types
export interface OAuthConfig {
  provider: OAuthProvider;
  client_id: string;
  authorize_url: string;
  scope: string[];
  enabled: boolean;
}

// Authentication API Types
export interface LoginRequest {
  provider: OAuthProvider;
  redirect_uri?: string;
}

export interface LoginResponse {
  authorization_url: string;
  state: string;
}

export interface CallbackRequest {
  code: string;
  state: string;
  provider: OAuthProvider;
}

export interface CallbackResponse {
  user: SessionUser;
  redirect_url?: string;
}

// Session Management Types
export interface SessionInfo {
  user: SessionUser;
  expires_at?: string;
  csrf_token?: string;
}

export interface LogoutResponse {
  success: boolean;
  redirect_url?: string;
}

// Authentication Error Types
export interface AuthError {
  code: string;
  message: string;
  provider?: string;
  details?: Record<string, unknown>;
}

// Authentication Events
export type AuthEvent =
  | { type: 'LOGIN_START'; provider: string }
  | { type: 'LOGIN_SUCCESS'; user: SessionUser }
  | { type: 'LOGIN_ERROR'; error: AuthError }
  | { type: 'LOGOUT_START' }
  | { type: 'LOGOUT_SUCCESS' }
  | { type: 'LOGOUT_ERROR'; error: AuthError }
  | { type: 'SESSION_EXPIRED' }
  | { type: 'SESSION_REFRESH'; user: SessionUser }
  | { type: 'CLEAR_ERROR' };

// Authentication Context Types
export interface AuthContextValue {
  state: AuthState;
  login: (provider: string) => Promise<LoginResponse>;
  logout: () => Promise<LogoutResponse>;
  refreshSession: () => Promise<void>;
  clearError: () => void;
}

// Route Protection Types
export interface ProtectedRouteProps {
  children: React.ReactNode;
  fallback?: React.ReactNode;
  redirectTo?: string;
}

export interface AuthGuardProps {
  children: React.ReactNode;
  requireAuth?: boolean;
  fallback?: React.ReactNode;
}

import {
  OAUTH_PROVIDER_NAMES,
  OAUTH_PROVIDER_ICONS,
  OAUTH_PROVIDER_COLORS,
  AUTH_STORAGE_KEYS as STORAGE_KEYS,
  API_ENDPOINTS,
} from '@/lib/constants';

// OAuth Provider Configuration
export const OAUTH_PROVIDERS: Record<
  OAuthProvider,
  { name: string; icon: string; color: string }
> = {
  [OAuthProvider.GITHUB]: {
    name: OAUTH_PROVIDER_NAMES.GITHUB,
    icon: OAUTH_PROVIDER_ICONS.GITHUB,
    color: OAUTH_PROVIDER_COLORS.GITHUB,
  },
  [OAuthProvider.MICROSOFT]: {
    name: OAUTH_PROVIDER_NAMES.MICROSOFT,
    icon: OAUTH_PROVIDER_ICONS.MICROSOFT,
    color: OAUTH_PROVIDER_COLORS.MICROSOFT,
  },
  [OAuthProvider.DISCORD]: {
    name: OAUTH_PROVIDER_NAMES.DISCORD,
    icon: OAUTH_PROVIDER_ICONS.DISCORD,
    color: OAUTH_PROVIDER_COLORS.DISCORD,
  },
  [OAuthProvider.GENERIC]: {
    name: OAUTH_PROVIDER_NAMES.GENERIC,
    icon: OAUTH_PROVIDER_ICONS.GENERIC,
    color: OAUTH_PROVIDER_COLORS.GENERIC,
  },
} as const;

// Re-export constants for backward compatibility
export const AUTH_STORAGE_KEYS = STORAGE_KEYS;
export const AUTH_ENDPOINTS = API_ENDPOINTS.AUTH;
