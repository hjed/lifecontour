/**
 * @jest-environment jsdom
 */

import { render, screen } from '@testing-library/react';
import { useRouter, usePathname } from 'next/navigation';
import { useAuth } from '@/lib/auth/AuthProvider';
import FavouritesPage from '../page';

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

describe('FavouritesPage', () => {
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

    mockUsePathname.mockReturnValue('/contacts/favourites');

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

  it('renders the favourites page with correct title and description', () => {
    render(<FavouritesPage />);
    
    // Check main heading
    expect(screen.getByRole('heading', { level: 1, name: 'Favourite Contacts' })).toBeInTheDocument();
    
    // Check description
    expect(screen.getByText('Your starred contacts will appear here.')).toBeInTheDocument();
  });

  it('displays coming soon card with star icon', () => {
    render(<FavouritesPage />);
    
    // Check card title with star icon
    expect(screen.getByText('Coming Soon')).toBeInTheDocument();
    
    // Check card content
    expect(screen.getByText(/The favourites functionality will be implemented in ITER1.5-004/)).toBeInTheDocument();
    expect(screen.getByText(/You'll be able to star your important contacts and view them here/)).toBeInTheDocument();
  });

  it('has proper page structure with container and spacing', () => {
    const { container } = render(<FavouritesPage />);
    
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

    render(<FavouritesPage />);

    // When not authenticated, AuthGuard should handle the redirect
    // The page content should not be rendered
    expect(screen.queryByText('Favourite Contacts')).not.toBeInTheDocument();
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

    render(<FavouritesPage />);

    // When loading, AuthGuard should show loading state
    // The page content should not be rendered yet
    expect(screen.queryByText('Favourite Contacts')).not.toBeInTheDocument();
  });

  it('has proper semantic HTML structure', () => {
    render(<FavouritesPage />);
    
    // Check that the main heading is properly structured
    const heading = screen.getByRole('heading', { level: 1 });
    expect(heading).toHaveTextContent('Favourite Contacts');
    
    // Check that the description paragraph exists
    const description = screen.getByText('Your starred contacts will appear here.');
    expect(description.tagName.toLowerCase()).toBe('p');
  });

  it('mentions the correct iteration for implementation', () => {
    render(<FavouritesPage />);
    
    // Verify that it specifically mentions ITER1.5-004
    expect(screen.getByText(/ITER1.5-004/)).toBeInTheDocument();
  });

  it('has accessible card structure', () => {
    render(<FavouritesPage />);
    
    // The card should have proper heading structure
    const cardTitle = screen.getByText('Coming Soon');
    expect(cardTitle).toBeInTheDocument();
    
    // The card content should be readable
    const cardContent = screen.getByText(/The favourites functionality will be implemented/);
    expect(cardContent).toBeInTheDocument();
  });
});
