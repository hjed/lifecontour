/**
 * @jest-environment jsdom
 */

import { render, screen, waitFor } from '@testing-library/react';
import { useRouter, usePathname } from 'next/navigation';
import { AuthGuard, withAuth } from '../AuthGuard';
import { useAuth } from '@/lib/auth/AuthProvider';
import { AuthState, SessionUser, OAuthProvider } from '@/types/auth';
import { createMockAppRouter } from '@/test-utils/mock-router';

// Mock Next.js navigation
jest.mock('next/navigation', () => ({
  useRouter: jest.fn(),
  usePathname: jest.fn(),
}));

// Mock auth provider
jest.mock('@/lib/auth/AuthProvider', () => ({
  useAuth: jest.fn(),
}));

// Test helper to create mock SessionUser
const createMockUser = (overrides: Partial<SessionUser> = {}): SessionUser => ({
  id: '1',
  email: 'test@example.com',
  name: 'Test User',
  provider: OAuthProvider.GITHUB,
  provider_id: 'github_123',
  created_at: '2023-01-01T00:00:00Z',
  last_login: '2023-01-01T00:00:00Z',
  ...overrides,
});

// Mock UI components
jest.mock('@/components/ui/card', () => ({
  Card: ({
    children,
    className,
  }: {
    children?: React.ReactNode;
    className?: string;
  }) => <div className={className}>{children}</div>,
  CardContent: ({
    children,
    className,
  }: {
    children?: React.ReactNode;
    className?: string;
  }) => <div className={className}>{children}</div>,
  CardDescription: ({ children }: { children?: React.ReactNode }) => (
    <div>{children}</div>
  ),
  CardHeader: ({
    children,
    className,
  }: {
    children?: React.ReactNode;
    className?: string;
  }) => <div className={className}>{children}</div>,
  CardTitle: ({
    children,
    className,
  }: {
    children?: React.ReactNode;
    className?: string;
  }) => <div className={className}>{children}</div>,
}));

jest.mock('@/components/ui/skeleton', () => ({
  Skeleton: ({ className }: { className?: string }) => (
    <div className={className} data-testid='skeleton' />
  ),
}));

const mockRouter = createMockAppRouter();

const mockUseRouter = useRouter as jest.MockedFunction<typeof useRouter>;
const mockUsePathname = usePathname as jest.MockedFunction<typeof usePathname>;
const mockUseAuth = useAuth as jest.MockedFunction<typeof useAuth>;

describe('AuthGuard', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockUseRouter.mockReturnValue(mockRouter);
    mockUsePathname.mockReturnValue('/test-path');
  });

  describe('when authentication is loading', () => {
    beforeEach(() => {
      mockUseAuth.mockReturnValue({
        state: {
          isLoading: true,
          isAuthenticated: false,
          user: null,
          error: undefined,
        } as AuthState,
        login: jest.fn(),
        logout: jest.fn(),
        refreshSession: jest.fn(),
        clearError: jest.fn(),
      });
    });

    it('should show loading fallback by default', () => {
      render(
        <AuthGuard>
          <div>Protected content</div>
        </AuthGuard>
      );

      expect(screen.getByText('Loading')).toBeInTheDocument();
      expect(
        screen.getByText('Checking your authentication status')
      ).toBeInTheDocument();
      expect(screen.getByText('Please wait...')).toBeInTheDocument();
      expect(screen.getAllByTestId('skeleton')).toHaveLength(3);
      expect(screen.queryByText('Protected content')).not.toBeInTheDocument();
    });

    it('should show custom fallback when provided', () => {
      const customFallback = <div>Custom loading...</div>;

      render(
        <AuthGuard fallback={customFallback}>
          <div>Protected content</div>
        </AuthGuard>
      );

      expect(screen.getByText('Custom loading...')).toBeInTheDocument();
      expect(screen.queryByText('Loading')).not.toBeInTheDocument();
      expect(screen.queryByText('Protected content')).not.toBeInTheDocument();
    });

    it('should not redirect while loading', () => {
      render(
        <AuthGuard>
          <div>Protected content</div>
        </AuthGuard>
      );

      expect(mockRouter.push).not.toHaveBeenCalled();
    });
  });

  describe('when user is authenticated', () => {
    beforeEach(() => {
      mockUseAuth.mockReturnValue({
        state: {
          isLoading: false,
          isAuthenticated: true,
          user: createMockUser(),
          error: undefined,
        } as AuthState,
        login: jest.fn(),
        logout: jest.fn(),
        refreshSession: jest.fn(),
        clearError: jest.fn(),
      });
    });

    it('should render children when authentication is required', () => {
      render(
        <AuthGuard requireAuth={true}>
          <div>Protected content</div>
        </AuthGuard>
      );

      expect(screen.getByText('Protected content')).toBeInTheDocument();
      expect(screen.queryByText('Loading')).not.toBeInTheDocument();
    });

    it('should render children when authentication is not required', () => {
      render(
        <AuthGuard requireAuth={false}>
          <div>Public content</div>
        </AuthGuard>
      );

      expect(screen.getByText('Public content')).toBeInTheDocument();
    });

    it('should not redirect authenticated users', () => {
      render(
        <AuthGuard>
          <div>Protected content</div>
        </AuthGuard>
      );

      expect(mockRouter.push).not.toHaveBeenCalled();
    });
  });

  describe('when user is not authenticated', () => {
    beforeEach(() => {
      mockUseAuth.mockReturnValue({
        state: {
          isLoading: false,
          isAuthenticated: false,
          user: null,
          error: undefined,
        } as AuthState,
        login: jest.fn(),
        logout: jest.fn(),
        refreshSession: jest.fn(),
        clearError: jest.fn(),
      });
    });

    it('should redirect to login when authentication is required', async () => {
      render(
        <AuthGuard requireAuth={true}>
          <div>Protected content</div>
        </AuthGuard>
      );

      await waitFor(() => {
        expect(mockRouter.push).toHaveBeenCalledWith(
          '/auth/login?redirect=%2Ftest-path'
        );
      });
    });

    it('should show fallback while redirecting', () => {
      render(
        <AuthGuard requireAuth={true}>
          <div>Protected content</div>
        </AuthGuard>
      );

      expect(screen.getByText('Loading')).toBeInTheDocument();
      expect(screen.queryByText('Protected content')).not.toBeInTheDocument();
    });

    it('should show custom fallback while redirecting', () => {
      const customFallback = <div>Redirecting...</div>;

      render(
        <AuthGuard requireAuth={true} fallback={customFallback}>
          <div>Protected content</div>
        </AuthGuard>
      );

      expect(screen.getByText('Redirecting...')).toBeInTheDocument();
      expect(screen.queryByText('Protected content')).not.toBeInTheDocument();
    });

    it('should render children when authentication is not required', () => {
      render(
        <AuthGuard requireAuth={false}>
          <div>Public content</div>
        </AuthGuard>
      );

      expect(screen.getByText('Public content')).toBeInTheDocument();
      expect(mockRouter.push).not.toHaveBeenCalled();
    });

    it('should handle different pathnames in redirect URL', async () => {
      mockUsePathname.mockReturnValue('/contacts/123');

      render(
        <AuthGuard requireAuth={true}>
          <div>Protected content</div>
        </AuthGuard>
      );

      await waitFor(() => {
        expect(mockRouter.push).toHaveBeenCalledWith(
          '/auth/login?redirect=%2Fcontacts%2F123'
        );
      });
    });
  });

  describe('requireAuth prop behavior', () => {
    it('should default to requiring authentication', async () => {
      mockUseAuth.mockReturnValue({
        state: {
          isLoading: false,
          isAuthenticated: false,
          user: null,
          error: undefined,
        } as AuthState,
        login: jest.fn(),
        logout: jest.fn(),
        refreshSession: jest.fn(),
        clearError: jest.fn(),
      });

      render(
        <AuthGuard>
          <div>Protected content</div>
        </AuthGuard>
      );

      await waitFor(() => {
        expect(mockRouter.push).toHaveBeenCalled();
      });
    });
  });
});

describe('withAuth HOC', () => {
  const TestComponent = ({ testProp }: { testProp: string }) => (
    <div>Test Component: {testProp}</div>
  );

  beforeEach(() => {
    jest.clearAllMocks();
    mockUseRouter.mockReturnValue(mockRouter);
    mockUsePathname.mockReturnValue('/test-path');
  });

  it('should wrap component with AuthGuard using default options', () => {
    mockUseAuth.mockReturnValue({
      state: {
        isLoading: false,
        isAuthenticated: true,
        user: createMockUser(),
        error: undefined,
      } as AuthState,
      login: jest.fn(),
      logout: jest.fn(),
      refreshSession: jest.fn(),
      clearError: jest.fn(),
    });

    const WrappedComponent = withAuth(TestComponent);

    render(<WrappedComponent testProp='hello' />);

    expect(screen.getByText('Test Component: hello')).toBeInTheDocument();
  });

  it('should pass through props to wrapped component', () => {
    mockUseAuth.mockReturnValue({
      state: {
        isLoading: false,
        isAuthenticated: true,
        user: createMockUser(),
        error: undefined,
      } as AuthState,
      login: jest.fn(),
      logout: jest.fn(),
      refreshSession: jest.fn(),
      clearError: jest.fn(),
    });

    const WrappedComponent = withAuth(TestComponent);

    render(<WrappedComponent testProp='world' />);

    expect(screen.getByText('Test Component: world')).toBeInTheDocument();
  });

  it('should respect requireAuth option', async () => {
    mockUseAuth.mockReturnValue({
      state: {
        isLoading: false,
        isAuthenticated: false,
        user: null,
        error: undefined,
      } as AuthState,
      login: jest.fn(),
      logout: jest.fn(),
      refreshSession: jest.fn(),
      clearError: jest.fn(),
    });

    const WrappedComponent = withAuth(TestComponent, { requireAuth: false });

    render(<WrappedComponent testProp='public' />);

    expect(screen.getByText('Test Component: public')).toBeInTheDocument();
    expect(mockRouter.push).not.toHaveBeenCalled();
  });

  it('should use custom fallback when provided', () => {
    mockUseAuth.mockReturnValue({
      state: {
        isLoading: true,
        isAuthenticated: false,
        user: null,
        error: undefined,
      } as AuthState,
      login: jest.fn(),
      logout: jest.fn(),
      refreshSession: jest.fn(),
      clearError: jest.fn(),
    });

    const customFallback = <div>Custom HOC loading...</div>;
    const WrappedComponent = withAuth(TestComponent, {
      fallback: customFallback,
    });

    render(<WrappedComponent testProp='test' />);

    expect(screen.getByText('Custom HOC loading...')).toBeInTheDocument();
    expect(screen.queryByText('Test Component: test')).not.toBeInTheDocument();
  });
});
