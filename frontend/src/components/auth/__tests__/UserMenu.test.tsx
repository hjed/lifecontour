/**
 * @jest-environment jsdom
 */

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { UserMenu } from '../UserMenu';
import { useAuth } from '@/lib/auth/AuthProvider';
import { OAuthProvider, type AuthContextValue } from '@/types/auth';
import { SOURCE_CODE_URL } from '@/lib/constants';

jest.mock('@/lib/auth/AuthProvider', () => ({
  useAuth: jest.fn(),
}));

const mockUseAuth = useAuth as jest.MockedFunction<typeof useAuth>;

function mockAuth(isAuthenticated: boolean): void {
  const value: AuthContextValue = {
    state: {
      isLoading: false,
      isAuthenticated,
      user: isAuthenticated
        ? {
            id: '1',
            email: 'test@example.com',
            name: 'Test User',
            provider: OAuthProvider.GITHUB,
            provider_id: 'github_123',
            created_at: '2023-01-01T00:00:00Z',
            last_login: '2023-01-01T00:00:00Z',
          }
        : null,
    },
    login: jest.fn(),
    logout: jest.fn(),
    refreshSession: jest.fn(),
    clearError: jest.fn(),
  };
  mockUseAuth.mockReturnValue(value);
}

async function openMenu(): Promise<void> {
  await userEvent.setup().click(screen.getByTestId('user-menu'));
}

describe('UserMenu', () => {
  it('renders nothing when signed out', () => {
    mockAuth(false);
    const { container } = render(<UserMenu />);
    expect(container).toBeEmptyDOMElement();
  });

  it('links to the source code in a new tab', async () => {
    mockAuth(true);
    render(<UserMenu />);
    await openMenu();

    const link = await screen.findByRole('menuitem', { name: /source code/i });
    expect(link).toHaveAttribute('href', SOURCE_CODE_URL);
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
    expect(link).toHaveAccessibleName('Source code (opens in a new tab)');
  });
});
