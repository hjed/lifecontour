'use client';

/**
 * Authentication provider and context for managing user sessions.
 *
 * Implements OAuth2 session-based authentication with the backend
 * following the AI guidelines for clean dependency injection.
 */

import {
  createContext,
  useContext,
  useReducer,
  useEffect,
  ReactNode,
} from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import {
  AuthState,
  AuthContextValue,
  AuthEvent,
  SessionUser,
  LoginResponse,
  LogoutResponse,
} from '@/types/auth';
import {
  API_ENDPOINTS,
  HTTP_HEADERS,
  ERROR_MESSAGES,
  SUCCESS_MESSAGES,
} from '@/lib/constants';
import { clearCachedTimezone } from '@/lib/api/settings';

// Initial auth state
const initialState: AuthState = {
  user: null,
  isLoading: true, // Start with loading true until session check completes
  isAuthenticated: false,
  error: undefined,
};

// Auth reducer for state management
function authReducer(state: AuthState, event: AuthEvent): AuthState {
  switch (event.type) {
    case 'LOGIN_START':
      return {
        ...state,
        isLoading: true,
        error: undefined,
      };

    case 'LOGIN_SUCCESS':
      return {
        ...state,
        user: event.user,
        isAuthenticated: true,
        isLoading: false,
        error: undefined,
      };

    case 'LOGIN_ERROR':
      return {
        ...state,
        user: null,
        isAuthenticated: false,
        isLoading: false,
        error: event.error.message,
      };

    case 'LOGOUT_START':
      return {
        ...state,
        isLoading: true,
        error: undefined,
      };

    case 'LOGOUT_SUCCESS':
      return {
        ...state,
        user: null,
        isAuthenticated: false,
        isLoading: false,
        error: undefined,
      };

    case 'LOGOUT_ERROR':
      return {
        ...state,
        isLoading: false,
        error: event.error.message,
      };

    case 'SESSION_EXPIRED':
      return {
        ...state,
        user: null,
        isAuthenticated: false,
        isLoading: false,
        error: state.isAuthenticated
          ? ERROR_MESSAGES.SESSION_EXPIRED
          : undefined,
      };

    case 'SESSION_REFRESH':
      return {
        ...state,
        user: event.user,
        isAuthenticated: true,
        isLoading: false,
        error: undefined,
      };

    case 'CLEAR_ERROR':
      return {
        ...state,
        error: undefined,
      };

    default:
      return state;
  }
}

// Auth context
const AuthContext = createContext<AuthContextValue | null>(null);

// Auth provider props
interface AuthProviderProps {
  children: ReactNode;
}

export function AuthProvider({ children }: AuthProviderProps) {
  const [state, dispatch] = useReducer(authReducer, initialState);
  const queryClient = useQueryClient();

  // Check session on mount
  const {
    data: sessionUser,
    isLoading: isSessionLoading,
    error: sessionError,
  } = useQuery({
    queryKey: ['auth', 'session'],
    queryFn: async (): Promise<SessionUser | null> => {
      try {
        const response = await fetch(API_ENDPOINTS.AUTH.SESSION, {
          credentials: 'include',
        });

        if (!response.ok) {
          if (response.status === 401 || response.status === 403) {
            return null;
          }
          throw new Error(
            `Session check failed with status ${response.status}`
          );
        }

        const data = await response.json();
        // Backend returns { authenticated: boolean, user: SessionUser | null }
        return data.authenticated ? data.user : null;
      } catch (err) {
        // If it's already a handled error status, rethrow it
        if (
          err instanceof Error &&
          err.message.startsWith('Session check failed')
        ) {
          throw err;
        }
        // Otherwise it's a network error
        throw new Error(
          err instanceof Error ? err.message : 'Network error checking session'
        );
      }
    },
    staleTime: 5 * 60 * 1000, // 5 minutes
    retry: 2, // Retry twice on network or server errors to handle transient glitches
  });

  // Update auth state when session data changes
  useEffect(() => {
    if (isSessionLoading) {
      // Keep loading state while session is being checked
      return;
    }

    if (sessionError) {
      // On network/server errors, treat user as not authenticated but clear error
      // so we don't display a false "Session expired" message
      dispatch({ type: 'SESSION_EXPIRED' });
      dispatch({ type: 'CLEAR_ERROR' });
      clearCachedTimezone();
      return;
    }

    if (sessionUser) {
      dispatch({ type: 'SESSION_REFRESH', user: sessionUser });
    } else {
      // Session check complete, no user found
      dispatch({ type: 'SESSION_EXPIRED' });
      // No authenticated user means no cached zone. An explicit logout is not
      // the only way a session ends — a server-side expiry, a failed check and
      // an unauthenticated first load all land here without going near the
      // logout mutation — and the cache is keyed by browser rather than by
      // account, so anything left behind would stand in for whoever signs in
      // next while their own settings read is still in flight.
      clearCachedTimezone();
    }
  }, [sessionUser, isSessionLoading, sessionError]);

  // Login mutation
  const loginMutation = useMutation({
    mutationFn: async (provider: string): Promise<LoginResponse> => {
      const response = await fetch(API_ENDPOINTS.AUTH.LOGIN, {
        method: 'POST',
        headers: {
          [HTTP_HEADERS.CONTENT_TYPE]: HTTP_HEADERS.APPLICATION_JSON,
        },
        body: JSON.stringify({ provider }),
        credentials: 'include',
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(
          errorData.errors?.[0]?.detail || ERROR_MESSAGES.LOGIN_FAILED
        );
      }

      return response.json();
    },
    onMutate: provider => {
      dispatch({ type: 'LOGIN_START', provider });
      // Store provider in sessionStorage for callback page
      sessionStorage.setItem('oauth_provider', provider);
    },
    onSuccess: data => {
      // Redirect to OAuth provider
      window.location.href = data.authorization_url;
    },
    onError: error => {
      dispatch({
        type: 'LOGIN_ERROR',
        error: { code: 'LOGIN_FAILED', message: error.message },
      });
      toast.error(ERROR_MESSAGES.LOGIN_FAILED, {
        description: error.message,
      });
    },
  });

  // Logout mutation
  const logoutMutation = useMutation({
    mutationFn: async (): Promise<LogoutResponse> => {
      const response = await fetch(API_ENDPOINTS.AUTH.LOGOUT, {
        method: 'POST',
        headers: {
          [HTTP_HEADERS.CONTENT_TYPE]: HTTP_HEADERS.APPLICATION_JSON,
        },
        credentials: 'include',
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(
          errorData.errors?.[0]?.detail || ERROR_MESSAGES.LOGOUT_FAILED
        );
      }

      return response.json();
    },
    onMutate: () => {
      dispatch({ type: 'LOGOUT_START' });
    },
    onSuccess: () => {
      dispatch({ type: 'LOGOUT_SUCCESS' });
      queryClient.clear();
      // `queryClient.clear()` empties the in-memory caches; the timezone also
      // has a localStorage one, and that is keyed by browser rather than by
      // account. The session effect clears it on every unauthenticated
      // settlement too, but that runs a refetch later — clearing here closes
      // the window rather than waiting for it.
      clearCachedTimezone();
      toast.success(SUCCESS_MESSAGES.SIGNED_OUT);
    },
    onError: error => {
      dispatch({
        type: 'LOGOUT_ERROR',
        error: { code: 'LOGOUT_FAILED', message: error.message },
      });
      toast.error(ERROR_MESSAGES.LOGOUT_FAILED, {
        description: error.message,
      });
    },
  });

  // Auth context value
  const contextValue: AuthContextValue = {
    state,
    login: (provider: string) => {
      loginMutation.mutate(provider);
      return Promise.resolve({} as LoginResponse);
    },
    logout: () => {
      logoutMutation.mutate();
      return Promise.resolve({} as LogoutResponse);
    },
    refreshSession: async () => {
      // Invalidate and refetch the session query, waiting for completion
      await queryClient.invalidateQueries({ queryKey: ['auth', 'session'] });
      await queryClient.refetchQueries({ queryKey: ['auth', 'session'] });
    },
    clearError: () => {
      dispatch({ type: 'CLEAR_ERROR' });
    },
  };

  return (
    <AuthContext.Provider value={contextValue}>{children}</AuthContext.Provider>
  );
}

// Hook to use auth context
export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);

  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }

  return context;
}
