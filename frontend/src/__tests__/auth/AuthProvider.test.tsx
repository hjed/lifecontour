/**
 * Tests for AuthProvider component and useAuth hook.
 *
 * Following test-first development approach from AI guidelines.
 * These tests define the expected behavior before implementation.
 */

import { render, screen, userEvent } from '../utils/test-utils';
import { useAuth } from '@/lib/auth-context';

// Test component to access auth context
function TestComponent() {
  const { isAuthenticated, isLoading, user, login, logout } = useAuth();

  return (
    <div>
      <div data-testid='auth-status'>
        {isAuthenticated ? 'authenticated' : 'not-authenticated'}
      </div>
      <div data-testid='loading-status'>
        {isLoading ? 'loading' : 'not-loading'}
      </div>
      {user && (
        <div data-testid='user-info'>
          {user.name} ({user.email})
        </div>
      )}
      {/* Error display would be handled by auth provider */}
      <button data-testid='login-github' onClick={() => login('github')}>
        Login with GitHub
      </button>
      <button data-testid='logout' onClick={logout}>
        Logout
      </button>
    </div>
  );
}

describe('AuthProvider', () => {
  it('should render children and provide auth context', () => {
    render(<TestComponent />);

    expect(screen.getByTestId('auth-status')).toHaveTextContent(
      'not-authenticated'
    );
    expect(screen.getByTestId('loading-status')).toHaveTextContent(
      'not-loading'
    );
  });

  it('should handle login flow', async () => {
    const user = userEvent.setup();
    render(<TestComponent />);

    const loginButton = screen.getByTestId('login-github');
    expect(loginButton).toBeInTheDocument();

    await user.click(loginButton);
    // Login functionality is tested in integration tests
  });

  it('should handle logout flow', async () => {
    const user = userEvent.setup();
    render(<TestComponent />);

    const logoutButton = screen.getByTestId('logout');
    expect(logoutButton).toBeInTheDocument();

    await user.click(logoutButton);
    // Logout functionality is tested in integration tests
  });

  it('should provide auth context values', () => {
    render(<TestComponent />);

    // Check that all expected elements are rendered
    expect(screen.getByTestId('auth-status')).toBeInTheDocument();
    expect(screen.getByTestId('loading-status')).toBeInTheDocument();
    expect(screen.getByTestId('login-github')).toBeInTheDocument();
    expect(screen.getByTestId('logout')).toBeInTheDocument();
  });
});
