/**
 * @jest-environment jsdom
 */

import { render, screen } from '@testing-library/react';
import { useParams, useRouter, usePathname } from 'next/navigation';
import { useAuth } from '@/lib/auth/AuthProvider';
import ContactGroupPage from '../page';

// Mock Next.js navigation
jest.mock('next/navigation', () => ({
  useParams: jest.fn(),
  useRouter: jest.fn(),
  usePathname: jest.fn(),
}));

// Mock the AuthProvider
jest.mock('@/lib/auth/AuthProvider', () => ({
  useAuth: jest.fn(),
}));

const mockUseParams = useParams as jest.MockedFunction<typeof useParams>;
const mockUseRouter = useRouter as jest.MockedFunction<typeof useRouter>;
const mockUsePathname = usePathname as jest.MockedFunction<typeof usePathname>;
const mockUseAuth = useAuth as jest.MockedFunction<typeof useAuth>;

describe('ContactGroupPage', () => {
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

    mockUsePathname.mockReturnValue('/contacts/groups/1');

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

  it('renders the contact group page with group ID 1', () => {
    mockUseParams.mockReturnValue({ id: '1' });
    
    render(<ContactGroupPage />);
    
    // Check main heading with group ID
    expect(screen.getByRole('heading', { level: 1, name: 'Contact Group 1' })).toBeInTheDocument();
    
    // Check description with group ID
    expect(screen.getByText('Contacts in group 1 will appear here.')).toBeInTheDocument();
  });

  it('renders the contact group page with group ID 2', () => {
    mockUseParams.mockReturnValue({ id: '2' });
    
    render(<ContactGroupPage />);
    
    // Check main heading with group ID
    expect(screen.getByRole('heading', { level: 1, name: 'Contact Group 2' })).toBeInTheDocument();
    
    // Check description with group ID
    expect(screen.getByText('Contacts in group 2 will appear here.')).toBeInTheDocument();
  });

  it('handles dynamic group IDs correctly', () => {
    mockUseParams.mockReturnValue({ id: 'custom-group' });
    
    render(<ContactGroupPage />);
    
    // Check main heading with custom group ID
    expect(screen.getByRole('heading', { level: 1, name: 'Contact Group custom-group' })).toBeInTheDocument();
    
    // Check description with custom group ID
    expect(screen.getByText('Contacts in group custom-group will appear here.')).toBeInTheDocument();
  });

  it('displays coming soon card with users icon', () => {
    mockUseParams.mockReturnValue({ id: '1' });
    
    render(<ContactGroupPage />);
    
    // Check card title
    expect(screen.getByText('Coming Soon')).toBeInTheDocument();
    
    // Check card content
    expect(screen.getByText(/The contact groups functionality will be implemented in ITER1.5-004/)).toBeInTheDocument();
    expect(screen.getByText(/You'll be able to organize your contacts into groups and view them here/)).toBeInTheDocument();
  });

  it('has proper page structure with container and spacing', () => {
    mockUseParams.mockReturnValue({ id: '1' });
    
    const { container } = render(<ContactGroupPage />);
    
    // Check that the page has proper container structure
    const containerDiv = container.querySelector('.container');
    expect(containerDiv).toBeInTheDocument();
    expect(containerDiv).toHaveClass('mx-auto', 'px-4', 'py-8');
    
    // Check that there's a margin bottom on the header section
    const headerSection = container.querySelector('.mb-6');
    expect(headerSection).toBeInTheDocument();
  });

  it('renders within AuthGuard component', () => {
    mockUseParams.mockReturnValue({ id: '1' });

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

    render(<ContactGroupPage />);

    // When not authenticated, AuthGuard should handle the redirect
    // The page content should not be rendered
    expect(screen.queryByText('Contact Group 1')).not.toBeInTheDocument();
  });

  it('shows loading state when auth is loading', () => {
    mockUseParams.mockReturnValue({ id: '1' });

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

    render(<ContactGroupPage />);

    // When loading, AuthGuard should show loading state
    // The page content should not be rendered yet
    expect(screen.queryByText('Contact Group 1')).not.toBeInTheDocument();
  });

  it('has proper semantic HTML structure', () => {
    mockUseParams.mockReturnValue({ id: '1' });
    
    render(<ContactGroupPage />);
    
    // Check that the main heading is properly structured
    const heading = screen.getByRole('heading', { level: 1 });
    expect(heading).toHaveTextContent('Contact Group 1');
    
    // Check that the description paragraph exists
    const description = screen.getByText('Contacts in group 1 will appear here.');
    expect(description.tagName.toLowerCase()).toBe('p');
  });

  it('mentions the correct iteration for implementation', () => {
    mockUseParams.mockReturnValue({ id: '1' });
    
    render(<ContactGroupPage />);
    
    // Verify that it specifically mentions ITER1.5-004
    expect(screen.getByText(/ITER1.5-004/)).toBeInTheDocument();
  });

  it('has accessible card structure', () => {
    mockUseParams.mockReturnValue({ id: '1' });
    
    render(<ContactGroupPage />);
    
    // The card should have proper heading structure
    const cardTitle = screen.getByText('Coming Soon');
    expect(cardTitle).toBeInTheDocument();
    
    // The card content should be readable
    const cardContent = screen.getByText(/The contact groups functionality will be implemented/);
    expect(cardContent).toBeInTheDocument();
  });

  it('handles missing or undefined group ID gracefully', () => {
    mockUseParams.mockReturnValue({ id: undefined });
    
    render(<ContactGroupPage />);
    
    // Should still render but with undefined in the text
    expect(screen.getByRole('heading', { level: 1 })).toBeInTheDocument();
  });
});
