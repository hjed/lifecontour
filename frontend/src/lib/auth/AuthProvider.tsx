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
  OAuthProvider,
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

// Initial auth state
const initialState: AuthState = {
  user: null,
  isLoading: false,
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
        error: ERROR_MESSAGES.SESSION_EXPIRED,
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
  const { data: sessionUser } = useQuery({
    queryKey: ['auth', 'session'],
    queryFn: async (): Promise<SessionUser | null> => {
      try {
        const response = await fetch(API_ENDPOINTS.AUTH.SESSION, {
          credentials: 'include',
        });

        if (!response.ok) {
          return null;
        }

        const data = await response.json();
        return data.user || null;
      } catch {
        return null;
      }
    },
    staleTime: 5 * 60 * 1000, // 5 minutes
    retry: false,
  });

  // Update auth state when session data changes
  useEffect(() => {
    if (sessionUser) {
      dispatch({ type: 'SESSION_REFRESH', user: sessionUser });
    } else if (state.isAuthenticated) {
      dispatch({ type: 'SESSION_EXPIRED' });
    }
  }, [sessionUser, state.isAuthenticated]);

  // Login mutation
  const loginMutation = useMutation({
    mutationFn: async (provider: OAuthProvider): Promise<LoginResponse> => {
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
    },
    onSuccess: data => {
      // Redirect to OAuth provider
      window.location.href = data.authorize_url;
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
    login: (provider: OAuthProvider) => {
      loginMutation.mutate(provider);
      return Promise.resolve({} as LoginResponse);
    },
    logout: () => {
      logoutMutation.mutate();
      return Promise.resolve({} as LogoutResponse);
    },
    refreshSession: () =>
      queryClient.invalidateQueries({ queryKey: ['auth', 'session'] }),
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
