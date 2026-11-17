/**
 * @jest-environment jsdom
 */

import { render, screen } from '@testing-library/react';
import { Header } from '@/components/layout';
import { useAuth } from '@/lib/auth/AuthProvider';

jest.mock('@/lib/auth/AuthProvider', () => ({
  useAuth: jest.fn(),
}));

// The chrome around the New control is not under test here.
jest.mock('@/components/auth/UserMenu', () => ({
  UserMenu: () => <div data-testid='user-menu' />,
}));
jest.mock('@/components/search/GlobalSearch', () => ({
  GlobalSearch: () => <div data-testid='global-search' />,
}));
jest.mock('@/components/layout/Sidebar', () => ({
  MobileSidebar: () => null,
}));
jest.mock('@/lib/api/contacts', () => ({
  useCreateContact: jest.fn(),
}));
jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn() }),
}));

const mockUseAuth = useAuth as jest.MockedFunction<typeof useAuth>;

function mockAuthenticated(isAuthenticated: boolean) {
  mockUseAuth.mockReturnValue({
    state: { isAuthenticated },
  } as never);
}

describe('Header New control', () => {
  it('shows New when signed in', () => {
    mockAuthenticated(true);

    render(<Header />);

    const banner = screen.getByRole('banner');
    expect(screen.getByRole('button', { name: 'New' })).toHaveAttribute(
      'aria-haspopup',
      'dialog'
    );
    expect(banner).toContainElement(
      screen.getByRole('button', { name: 'New' })
    );
  });

  it('hides New when signed out', () => {
    mockAuthenticated(false);

    render(<Header />);

    expect(
      screen.queryByRole('button', { name: 'New' })
    ).not.toBeInTheDocument();
    expect(screen.getByText('Sign In')).toBeInTheDocument();
  });
});
