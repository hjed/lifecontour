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
  });

  it('should render login page with OAuth providers', () => {
    renderWithProviders(<LoginPage />);

    // Check page title and description
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(
      'Welcome Back'
    );
    expect(
      screen.getByText(/sign in to your personal management system/i)
    ).toBeInTheDocument();

    // Check OAuth provider buttons
    expect(
      screen.getByRole('button', { name: TEST_CONSTANTS.BUTTON_LABELS.GITHUB })
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

  it('should have proper accessibility attributes', () => {
    renderWithProviders(<LoginPage />);

    // Check ARIA labels and roles
    const githubButton = screen.getByRole('button', {
      name: TEST_CONSTANTS.BUTTON_LABELS.GITHUB,
    });
    expect(githubButton).toHaveAttribute('aria-label');

    // Check form structure
    const loginForm = screen.getByRole('main');
    expect(loginForm).toBeInTheDocument();
  });

  // Helper function to test OAuth provider login
  const testOAuthLogin = async (
    provider: 'github' | 'microsoft' | 'discord'
  ) => {
    const user = userEvent.setup();

    // Setup mocks
    (fetch as jest.Mock)
      .mockResolvedValueOnce(createMockResponses.sessionNotAuthenticated())
      .mockImplementationOnce(() =>
        createMockResponses.withDelay(
          createMockResponses.loginSuccess(provider)
        )
      );

    renderWithProviders(<LoginPage />);

    const buttonLabel =
      TEST_CONSTANTS.BUTTON_LABELS[
        provider.toUpperCase() as keyof typeof TEST_CONSTANTS.BUTTON_LABELS
      ];
    const button = screen.getByRole('button', { name: buttonLabel });

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

    // Setup mocks
    (fetch as jest.Mock)
      .mockResolvedValueOnce(createMockResponses.sessionNotAuthenticated())
      .mockResolvedValueOnce(createMockResponses.loginError());

    renderWithProviders(<LoginPage />);

    const githubButton = screen.getByRole('button', {
      name: TEST_CONSTANTS.BUTTON_LABELS.GITHUB,
    });
    await user.click(githubButton);

    // Should display error message
    expect(
      await screen.findByText(
        new RegExp(TEST_CONSTANTS.ERROR_MESSAGES.OAUTH_NOT_CONFIGURED, 'i')
      )
    ).toBeInTheDocument();
  });

  it('should be responsive and mobile-friendly', () => {
    renderWithProviders(<LoginPage />);

    // Check responsive classes are applied
    const container = screen.getByRole('main');
    expect(container).toHaveClass('container');

    // Check mobile-first responsive design
    const loginCard = container.querySelector('[class*="max-w"]');
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
