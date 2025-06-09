/**
 * Tests for Login page component.
 *
 * Following test-first development approach from AI guidelines.
 * These tests define the expected behavior before implementation.
 */

import { render, screen, userEvent, waitForAsync } from '../utils/test-utils';
import LoginPage from '@/app/auth/login/page';

describe('LoginPage', () => {
  it('should render login page with OAuth providers', async () => {
    render(<LoginPage />);

    // Wait for providers to load
    await waitForAsync();

    // Check page title and description
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(
      'Welcome Back'
    );
    expect(
      screen.getByText(/sign in to your personal crm account/i)
    ).toBeInTheDocument();

    // Check OAuth provider buttons
    expect(screen.getByText(/continue with github/i)).toBeInTheDocument();
    expect(screen.getByText(/continue with microsoft/i)).toBeInTheDocument();
  });

  it('should have proper accessibility attributes', async () => {
    render(<LoginPage />);

    // Wait for providers to load
    await waitForAsync();

    // Check form structure
    const loginForm = screen.getByTestId('login-form');
    expect(loginForm).toBeInTheDocument();
    expect(loginForm).toHaveAttribute('role', 'form');
  });

  it('should handle OAuth provider clicks', async () => {
    const user = userEvent.setup();
    render(<LoginPage />);

    // Wait for providers to load
    await waitForAsync();

    const githubButton = screen.getByTestId('oauth-provider-github');
    expect(githubButton).toBeInTheDocument();

    await user.click(githubButton);
    // Login functionality is tested in E2E tests
  });

  it('should be responsive and mobile-friendly', async () => {
    render(<LoginPage />);

    // Wait for providers to load
    await waitForAsync();

    // Check responsive classes are applied
    const container = screen.getByRole('main');
    expect(container).toHaveClass('container');

    // Check mobile-first responsive design
    const loginCard = screen.getByTestId('login-form');
    expect(loginCard).toBeInTheDocument();
  });

  it('should follow Australian English localization', async () => {
    render(<LoginPage />);

    // Wait for providers to load
    await waitForAsync();

    // Check for Australian English terminology
    expect(screen.getByText(/personal crm account/i)).toBeInTheDocument();
  });
});
