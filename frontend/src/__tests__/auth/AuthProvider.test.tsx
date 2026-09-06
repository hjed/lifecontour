/**
 * Tests for AuthProvider component and useAuth hook.
 *
 * Following test-first development approach from AI guidelines.
 * These tests define the expected behavior before implementation.
 */

import { screen, waitFor } from '@testing-library/react';
import {
  renderWithProviders,
  userEvent,
  setupMocks,
  createMockResponses,
  TEST_CONSTANTS,
} from '@/test-utils';
import { useAuth } from '@/lib/auth/AuthProvider';
import { TIMEZONE_STORAGE_KEY } from '@/lib/api/settings';
import { OAuthProvider } from '@/types/auth';

// Test component to access auth context
function TestComponent() {
  const { state, login, logout, clearError } = useAuth();

  return (
    <div>
      <div data-testid={TEST_CONSTANTS.TEST_IDS.AUTH_STATUS}>
        {state.isAuthenticated ? 'authenticated' : 'not-authenticated'}
      </div>
      <div data-testid={TEST_CONSTANTS.TEST_IDS.LOADING_STATUS}>
        {state.isLoading ? 'loading' : 'not-loading'}
      </div>
      {state.user && (
        <div data-testid={TEST_CONSTANTS.TEST_IDS.USER_INFO}>
          {state.user.name} ({state.user.email})
        </div>
      )}
      {state.error && (
        <div data-testid={TEST_CONSTANTS.TEST_IDS.ERROR_MESSAGE}>
          {state.error}
        </div>
      )}
      <button
        data-testid={TEST_CONSTANTS.TEST_IDS.LOGIN_GITHUB}
        onClick={() => login(OAuthProvider.GITHUB)}
      >
        Login with GitHub
      </button>
      <button data-testid={TEST_CONSTANTS.TEST_IDS.LOGOUT} onClick={logout}>
        Logout
      </button>
      <button
        data-testid={TEST_CONSTANTS.TEST_IDS.CLEAR_ERROR}
        onClick={clearError}
      >
        Clear Error
      </button>
    </div>
  );
}

describe('AuthProvider', () => {
  beforeEach(() => {
    setupMocks.clearMocks();
    setupMocks.fetch();
  });

  it('should render children and provide auth context', async () => {
    // Mock session check to return not authenticated
    (fetch as jest.Mock).mockResolvedValueOnce(
      createMockResponses.sessionNotAuthenticated()
    );

    renderWithProviders(<TestComponent />);

    // Wait for session check to complete
    await waitFor(() => {
      expect(
        screen.getByTestId(TEST_CONSTANTS.TEST_IDS.LOADING_STATUS)
      ).toHaveTextContent('not-loading');
    });

    expect(
      screen.getByTestId(TEST_CONSTANTS.TEST_IDS.AUTH_STATUS)
    ).toHaveTextContent('not-authenticated');
  });

  it('should handle login flow successfully', async () => {
    const user = userEvent.setup();

    // Setup mocks
    (fetch as jest.Mock)
      .mockResolvedValueOnce(createMockResponses.sessionNotAuthenticated())
      .mockResolvedValueOnce(createMockResponses.loginSuccess('github'));

    setupMocks.windowLocation();

    renderWithProviders(<TestComponent />);

    await user.click(screen.getByTestId(TEST_CONSTANTS.TEST_IDS.LOGIN_GITHUB));

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider: 'github' }),
        credentials: 'include',
      });
    });
  });

  it('should handle login error', async () => {
    const user = userEvent.setup();

    // Setup mocks
    (fetch as jest.Mock)
      .mockResolvedValueOnce(createMockResponses.sessionNotAuthenticated())
      .mockResolvedValueOnce(createMockResponses.loginError());

    renderWithProviders(<TestComponent />);

    await user.click(screen.getByTestId(TEST_CONSTANTS.TEST_IDS.LOGIN_GITHUB));

    await waitFor(
      () => {
        expect(
          screen.getByTestId(TEST_CONSTANTS.TEST_IDS.ERROR_MESSAGE)
        ).toHaveTextContent(TEST_CONSTANTS.ERROR_MESSAGES.OAUTH_NOT_CONFIGURED);
      },
      { timeout: 3000 }
    );
  });

  it('should handle logout successfully', async () => {
    const user = userEvent.setup();

    // Setup mocks
    (fetch as jest.Mock)
      .mockResolvedValueOnce(createMockResponses.sessionNotAuthenticated())
      .mockResolvedValueOnce(createMockResponses.logoutSuccess());

    renderWithProviders(<TestComponent />);

    await user.click(screen.getByTestId(TEST_CONSTANTS.TEST_IDS.LOGOUT));

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith('/api/auth/logout', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
      });
    });
  });

  /**
   * The cached timezone is keyed by *browser*, not by account, and it is what
   * `getDefaultTimezone` answers with while a settings read is in flight. Left
   * behind at logout it would anchor the next user's new events — and, for a
   * user who configures no zone of their own, their journal date writes — in
   * the previous account's zone (#1401 review).
   */
  it('clears the cached timezone so it cannot outlive the session', async () => {
    const user = userEvent.setup();
    localStorage.setItem(TIMEZONE_STORAGE_KEY, 'America/New_York');

    (fetch as jest.Mock)
      .mockResolvedValueOnce(createMockResponses.sessionNotAuthenticated())
      .mockResolvedValueOnce(createMockResponses.logoutSuccess());

    renderWithProviders(<TestComponent />);

    await user.click(screen.getByTestId(TEST_CONSTANTS.TEST_IDS.LOGOUT));

    await waitFor(() => {
      expect(localStorage.getItem(TIMEZONE_STORAGE_KEY)).toBeNull();
    });
  });

  /**
   * An explicit logout is not the only way a session ends. A server-side
   * expiry, a failed session check and a plain unauthenticated first load all
   * dispatch `SESSION_EXPIRED` without going near the logout mutation, and a
   * cache left behind by any of them would stand in for the *next* account
   * while its own settings read is still in flight.
   */
  it('clears the cached timezone whenever no user is authenticated', async () => {
    localStorage.setItem(TIMEZONE_STORAGE_KEY, 'America/New_York');

    (fetch as jest.Mock).mockResolvedValueOnce(
      createMockResponses.sessionNotAuthenticated()
    );

    renderWithProviders(<TestComponent />);

    // No logout is performed: the session check alone settles unauthenticated.
    await waitFor(() => {
      expect(localStorage.getItem(TIMEZONE_STORAGE_KEY)).toBeNull();
    });
  });

  it('should clear error when clearError is called', async () => {
    const user = userEvent.setup();

    // Setup mocks
    (fetch as jest.Mock)
      .mockResolvedValueOnce(createMockResponses.sessionNotAuthenticated())
      .mockResolvedValueOnce(
        createMockResponses.loginError(TEST_CONSTANTS.ERROR_MESSAGES.TEST_ERROR)
      );

    renderWithProviders(<TestComponent />);

    // Trigger error
    await user.click(screen.getByTestId(TEST_CONSTANTS.TEST_IDS.LOGIN_GITHUB));

    await waitFor(
      () => {
        expect(
          screen.getByTestId(TEST_CONSTANTS.TEST_IDS.ERROR_MESSAGE)
        ).toHaveTextContent(TEST_CONSTANTS.ERROR_MESSAGES.TEST_ERROR);
      },
      { timeout: 3000 }
    );

    // Clear error
    await user.click(screen.getByTestId(TEST_CONSTANTS.TEST_IDS.CLEAR_ERROR));

    await waitFor(() => {
      expect(
        screen.queryByTestId(TEST_CONSTANTS.TEST_IDS.ERROR_MESSAGE)
      ).not.toBeInTheDocument();
    });
  });
});
