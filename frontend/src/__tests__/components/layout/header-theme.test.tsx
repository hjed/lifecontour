/**
 * @jest-environment jsdom
 */

import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ThemeProvider } from 'next-themes';
import { Header } from '@/components/layout/Header';
import { AuthProvider } from '@/lib/auth/AuthProvider';

// Mock next/link
jest.mock('next/link', () => {
  const MockLink = ({
    children,
    href,
  }: {
    children: React.ReactNode;
    href: string;
  }) => <a href={href}>{children}</a>;
  MockLink.displayName = 'MockLink';
  return MockLink;
});

// Mock next-themes
jest.mock('next-themes', () => ({
  ThemeProvider: ({ children }: { children: React.ReactNode }) => children,
  useTheme: () => ({
    theme: 'light',
    setTheme: jest.fn(),
  }),
}));

// Mock fetch for auth
global.fetch = jest.fn(() =>
  Promise.resolve({
    ok: false,
    json: () => Promise.resolve({ authenticated: false, user: null }),
  })
) as jest.Mock;

const TestWrapper = ({ children }: { children: React.ReactNode }) => {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <AuthProvider>{children}</AuthProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
};

describe('Header with Theme Toggle', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders theme toggle button when user is not authenticated', async () => {
    render(
      <TestWrapper>
        <Header />
      </TestWrapper>
    );

    // Wait for auth state to settle
    await screen.findByText('Sign In');

    // Theme toggle should be present
    const themeToggle = screen.getByTestId('theme-toggle');
    expect(themeToggle).toBeInTheDocument();
  });

  it('renders theme toggle button when user is authenticated', async () => {
    // Mock authenticated user
    global.fetch = jest.fn(() =>
      Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            authenticated: true,
            user: {
              id: '1',
              email: 'test@example.com',
              name: 'Test User',
            },
          }),
      })
    ) as jest.Mock;

    render(
      <TestWrapper>
        <Header />
      </TestWrapper>
    );

    // Wait for auth state to settle and user menu to appear
    await screen.findByTestId('user-menu');

    // Theme toggle should be present
    const themeToggle = screen.getByTestId('theme-toggle');
    expect(themeToggle).toBeInTheDocument();
  });

  it('positions theme toggle correctly in the header layout', async () => {
    render(
      <TestWrapper>
        <Header />
      </TestWrapper>
    );

    // Wait for auth state to settle
    await screen.findByText('Sign In');

    // Check that theme toggle is in the same container as sign in button
    const themeToggle = screen.getByTestId('theme-toggle');
    const signInButton = screen.getByText('Sign In');

    // Both should be in the header
    expect(themeToggle.closest('header')).toBe(signInButton.closest('header'));
  });
});
