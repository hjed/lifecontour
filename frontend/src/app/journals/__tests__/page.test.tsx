/**
 * @jest-environment jsdom
 */

import { render, screen } from '@testing-library/react';
import { useRouter, usePathname } from 'next/navigation';
import { useAuth } from '@/lib/auth/AuthProvider';
import JournalsPage from '../page';

// Mock Next.js navigation
jest.mock('next/navigation', () => ({
  useRouter: jest.fn(),
  usePathname: jest.fn(),
}));

// Mock the AuthProvider
jest.mock('@/lib/auth/AuthProvider', () => ({
  useAuth: jest.fn(),
}));

const mockUseRouter = useRouter as jest.MockedFunction<typeof useRouter>;
const mockUsePathname = usePathname as jest.MockedFunction<typeof usePathname>;
const mockUseAuth = useAuth as jest.MockedFunction<typeof useAuth>;

describe('JournalsPage', () => {
  beforeEach(() => {
    // Mock Next.js router hooks
    mockUseRouter.mockReturnValue({
      push: jest.fn(),
      replace: jest.fn(),
      back: jest.fn(),
      forward: jest.fn(),
      refresh: jest.fn(),
      prefetch: jest.fn(),
    } as any);

    mockUsePathname.mockReturnValue('/journals');

    // Mock authenticated user by default
    mockUseAuth.mockReturnValue({
      state: {
        user: { id: '1', email: 'test@example.com' },
        isLoading: false,
        isAuthenticated: true,
        error: undefined,
      },
      login: jest.fn(),
      logout: jest.fn(),
    });
  });

  afterEach(() => {
    jest.clearAllMocks();
  });

  it('renders the journals page with correct title and description', () => {
    render(<JournalsPage />);
    
    // Check main heading
    expect(screen.getByRole('heading', { level: 1, name: 'Journals' })).toBeInTheDocument();
    
    // Check description
    expect(screen.getByText('Your journal entries will appear here.')).toBeInTheDocument();
  });

  it('displays coming soon card with book icon', () => {
    render(<JournalsPage />);
    
    // Check card title
    expect(screen.getByText('Coming Soon')).toBeInTheDocument();
    
    // Check card content
    expect(screen.getByText(/The journal system will be implemented in a future iteration/)).toBeInTheDocument();
    expect(screen.getByText(/You'll be able to create and manage your personal journal entries here/)).toBeInTheDocument();
  });

  it('has proper page structure with container and spacing', () => {
    const { container } = render(<JournalsPage />);
    
    // Check that the page has proper container structure
    const containerDiv = container.querySelector('.container');
    expect(containerDiv).toBeInTheDocument();
    expect(containerDiv).toHaveClass('mx-auto', 'px-4', 'py-8');
    
    // Check that there's a margin bottom on the header section
    const headerSection = container.querySelector('.mb-6');
    expect(headerSection).toBeInTheDocument();
  });

  it('renders within AuthGuard component', () => {
    // Test that unauthenticated users are handled by AuthGuard
    mockUseAuth.mockReturnValue({
      state: {
        user: null,
        isLoading: false,
        isAuthenticated: false,
        error: undefined,
      },
      login: jest.fn(),
      logout: jest.fn(),
    });

    render(<JournalsPage />);

    // When not authenticated, AuthGuard should handle the redirect
    // The page content should not be rendered
    expect(screen.queryByText('Journals')).not.toBeInTheDocument();
  });

  it('shows loading state when auth is loading', () => {
    mockUseAuth.mockReturnValue({
      state: {
        user: null,
        isLoading: true,
        isAuthenticated: false,
        error: undefined,
      },
      login: jest.fn(),
      logout: jest.fn(),
    });

    render(<JournalsPage />);

    // When loading, AuthGuard should show loading state
    // The page content should not be rendered yet
    expect(screen.queryByText('Journals')).not.toBeInTheDocument();
  });

  it('has proper semantic HTML structure', () => {
    render(<JournalsPage />);
    
    // Check that the main heading is properly structured
    const heading = screen.getByRole('heading', { level: 1 });
    expect(heading).toHaveTextContent('Journals');
    
    // Check that the description paragraph exists
    const description = screen.getByText('Your journal entries will appear here.');
    expect(description.tagName.toLowerCase()).toBe('p');
  });

  it('mentions future iteration for implementation', () => {
    render(<JournalsPage />);
    
    // Verify that it mentions future iteration (not specific like the others)
    expect(screen.getByText(/future iteration/)).toBeInTheDocument();
  });

  it('has accessible card structure', () => {
    render(<JournalsPage />);
    
    // The card should have proper heading structure
    const cardTitle = screen.getByText('Coming Soon');
    expect(cardTitle).toBeInTheDocument();
    
    // The card content should be readable
    const cardContent = screen.getByText(/The journal system will be implemented/);
    expect(cardContent).toBeInTheDocument();
  });

  it('uses appropriate icon color for journals', () => {
    const { container } = render(<JournalsPage />);
    
    // Check that the BookOpen icon has the green color class
    // This tests that the styling is consistent with the design
    const iconElement = container.querySelector('.text-green-500');
    expect(iconElement).toBeInTheDocument();
  });

  it('has consistent styling with other placeholder pages', () => {
    const { container } = render(<JournalsPage />);

    // Check for consistent card structure using more specific selectors
    const cardElement = container.querySelector('[class*="card"]');
    expect(cardElement).toBeInTheDocument();

    // Check that the card contains the expected content structure
    expect(screen.getByText('Coming Soon')).toBeInTheDocument();
    expect(screen.getByText(/The journal system will be implemented/)).toBeInTheDocument();
  });

  it('provides clear user expectations', () => {
    render(<JournalsPage />);
    
    // Check that the page clearly explains what will be available
    expect(screen.getByText(/create and manage your personal journal entries/)).toBeInTheDocument();
  });
});
