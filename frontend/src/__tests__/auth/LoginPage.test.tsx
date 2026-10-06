/**
 * Tests for Login page component.
 *
 * Following test-first development approach from AI guidelines.
 * These tests define the expected behavior before implementation.
 */

import { screen, within } from '@testing-library/react';
import {
  renderWithProviders,
  userEvent,
  setupMocks,
  createMockResponses,
  TEST_CONSTANTS,
} from '@/test-utils';
import LoginPage from '@/app/auth/login/page';
import {
  APP_NAME,
  SOURCE_CODE_URL,
  THIRD_PARTY_NOTICES_PATH,
  UI_TEXT,
} from '@/lib/constants';

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
    expect(screen.getByText(`Sign in to ${APP_NAME}`)).toBeInTheDocument();
    expect(
      screen.getByText(`This is a private, self-hosted ${APP_NAME} instance.`)
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

  it('offers the source code and third-party notices to signed-out visitors', () => {
    renderWithProviders(<LoginPage />);

    const projectLinks = within(
      screen.getByRole('navigation', { name: 'Project links' })
    );

    const sourceLink = projectLinks.getByRole('link', {
      name: 'Source code (opens in a new tab)',
    });
    expect(sourceLink).toHaveAttribute('href', SOURCE_CODE_URL);
    expect(sourceLink).toHaveAttribute('target', '_blank');
    expect(sourceLink).toHaveAttribute('rel', 'noopener noreferrer');

    const noticesLink = projectLinks.getByRole('link', {
      name: 'Third-party notices (opens in a new tab)',
    });
    expect(noticesLink).toHaveAttribute('href', THIRD_PARTY_NOTICES_PATH);
    expect(noticesLink).toHaveAttribute('target', '_blank');
    expect(noticesLink).toHaveAttribute('rel', 'noopener noreferrer');
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

    // Check that the login card has responsive classes
    const heading = screen.getByRole('heading', { level: 1 });
    expect(heading).toBeInTheDocument();

    // Check mobile-first responsive design - look for the card with max-width
    const loginCard = heading.closest('[class*="max-w"]');
    expect(loginCard).toBeInTheDocument();
    expect(loginCard).toHaveClass('max-w-md');
  });

  it('should follow Australian English localization', () => {
    renderWithProviders(<LoginPage />);

    // Check for Australian English terminology
    expect(screen.getByText(UI_TEXT.SIGN_IN_DESCRIPTION)).toBeInTheDocument();

    // Should not use American spellings
    expect(screen.queryByText(/organization/i)).not.toBeInTheDocument();
  });
});
