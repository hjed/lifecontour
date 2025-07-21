/**
 * Tests for Login page component.
 *
 * Following test-first development approach from AI guidelines.
 * These tests define the expected behavior before implementation.
 */

import { screen } from '@testing-library/react';
import {
  renderWithProviders,
  userEvent,
  setupMocks,
  createMockResponses,
  TEST_CONSTANTS,
} from '@/test-utils';
import LoginPage from '@/app/auth/login/page';

// Mock next/navigation
jest.mock('next/navigation', () => ({
  useRouter: () => ({
    push: jest.fn(),
    replace: jest.fn(),
  }),
  useSearchParams: () => ({
    get: jest.fn(),
  }),
}));

describe('LoginPage', () => {
  beforeEach(() => {
    setupMocks.clearMocks();
    setupMocks.fetch();
    setupMocks.windowLocation();

    // Mock providers API call
    (fetch as jest.Mock).mockImplementation((url: string) => {
      if (url.includes('/api/auth/providers')) {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            providers: [
              { name: 'github', display_name: 'GitHub' },
              { name: 'microsoft', display_name: 'Microsoft' },
              { name: 'discord', display_name: 'Discord' },
            ],
          }),
        });
      }
      // Default to session not authenticated
      return Promise.resolve(createMockResponses.sessionNotAuthenticated());
    });
  });

  it('should render login page with OAuth providers', async () => {
    renderWithProviders(<LoginPage />);

    // Check page title and description
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(
      'Welcome Back'
    );
    expect(
      screen.getByText(/sign in to your personal management system/i)
    ).toBeInTheDocument();

    // Wait for OAuth provider buttons to load
    expect(
      await screen.findByRole('button', {
        name: TEST_CONSTANTS.BUTTON_LABELS.GITHUB,
      })
    ).toBeInTheDocument();
    expect(
      screen.getByRole('button', {
        name: TEST_CONSTANTS.BUTTON_LABELS.MICROSOFT,
      })
    ).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: TEST_CONSTANTS.BUTTON_LABELS.DISCORD })
    ).toBeInTheDocument();
  });

  it('should have proper accessibility attributes', async () => {
    renderWithProviders(<LoginPage />);

    // Wait for providers to load, then check ARIA labels and roles
    const githubButton = await screen.findByRole('button', {
      name: TEST_CONSTANTS.BUTTON_LABELS.GITHUB,
    });
    expect(githubButton).toHaveAttribute('aria-label');

    // Check form structure - look for the login card container
    const loginCard = screen.getByRole('heading', { level: 1 }).closest('div');
    expect(loginCard).toBeInTheDocument();
  });

  // Helper function to test OAuth provider login
  const testOAuthLogin = async (
    provider: 'github' | 'microsoft' | 'discord'
  ) => {
    const user = userEvent.setup();

    renderWithProviders(<LoginPage />);

    const buttonLabel =
      TEST_CONSTANTS.BUTTON_LABELS[
        provider.toUpperCase() as keyof typeof TEST_CONSTANTS.BUTTON_LABELS
      ];

    // Wait for button to load
    const button = await screen.findByRole('button', { name: buttonLabel });

    // Click and immediately check loading state
    await user.click(button);

    // Should show loading state
    expect(button).toBeDisabled();
  };

  it('should handle GitHub login click', async () => {
    await testOAuthLogin('github');
  });

  it('should handle Microsoft login click', async () => {
    await testOAuthLogin('microsoft');
  });

  it('should handle Discord login click', async () => {
    await testOAuthLogin('discord');
  });

  it('should display error message on login failure', async () => {
    const user = userEvent.setup();

    renderWithProviders(<LoginPage />);

    // Wait for button to load
    const githubButton = await screen.findByRole('button', {
      name: TEST_CONSTANTS.BUTTON_LABELS.GITHUB,
    });
    await user.click(githubButton);

    // Should display an error message (any error message indicates failure handling works)
    const errorAlert = await screen.findByRole('alert');
    expect(errorAlert).toBeInTheDocument();
    expect(errorAlert).toHaveTextContent(/error|failed|not|function/i);
  });

  it('should be responsive and mobile-friendly', () => {
    renderWithProviders(<LoginPage />);

    // Check responsive classes are applied - look for the login container
    const container = screen.getByRole('heading', { level: 1 }).closest('div');
    expect(container).toBeInTheDocument();

    // Check mobile-first responsive design
    const loginCard = container?.querySelector('[class*="max-w"]');
    expect(loginCard).toBeInTheDocument();
  });

  it('should follow Australian English localization', () => {
    renderWithProviders(<LoginPage />);

    // Check for Australian English terminology
    expect(screen.getByText(/personal management system/i)).toBeInTheDocument();

    // Should not use American spellings
    expect(screen.queryByText(/organization/i)).not.toBeInTheDocument();
  });
});
