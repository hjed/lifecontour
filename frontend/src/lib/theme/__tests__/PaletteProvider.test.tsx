/**
 * @jest-environment jsdom
 */

import { render, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { useAuth } from '@/lib/auth/AuthProvider';
import { PaletteProvider } from '../PaletteProvider';
import { PALETTE_ATTRIBUTE, PALETTE_STORAGE_KEY } from '../palettes';

jest.mock('@/lib/auth/AuthProvider', () => ({ useAuth: jest.fn() }));

const mockUseAuth = useAuth as jest.MockedFunction<typeof useAuth>;
const mockFetch = jest.fn();
globalThis.fetch = mockFetch;

const root = document.documentElement;

function signedIn(isAuthenticated: boolean) {
  mockUseAuth.mockReturnValue({
    state: { isAuthenticated, isLoading: false, user: null, error: null },
  } as unknown as ReturnType<typeof useAuth>);
}

function settingsRespondWith(themePalette: string | null) {
  mockFetch.mockResolvedValue({
    ok: true,
    json: async () => ({
      data: {
        id: 'user-1',
        type: 'user_settings',
        attributes: {
          timezone: null,
          default_country: null,
          theme_palette: themePalette,
        },
      },
    }),
  } as Response);
}

function renderProvider() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <PaletteProvider>
        <p>app</p>
      </PaletteProvider>
    </QueryClientProvider>
  );
}

describe('PaletteProvider', () => {
  beforeEach(() => {
    localStorage.clear();
    root.removeAttribute(PALETTE_ATTRIBUTE);
    mockFetch.mockReset();
  });

  it("applies and caches the account's palette once it loads", async () => {
    signedIn(true);
    settingsRespondWith('emerald');

    renderProvider();

    await waitFor(() =>
      expect(root.getAttribute(PALETTE_ATTRIBUTE)).toBe('emerald')
    );
    expect(localStorage.getItem(PALETTE_STORAGE_KEY)).toBe('emerald');
  });

  it('lets the account override a stale cached palette', async () => {
    // Another device chose the default since this browser cached emerald.
    localStorage.setItem(PALETTE_STORAGE_KEY, 'emerald');
    root.setAttribute(PALETTE_ATTRIBUTE, 'emerald');
    signedIn(true);
    settingsRespondWith(null);

    renderProvider();

    await waitFor(() =>
      expect(root.hasAttribute(PALETTE_ATTRIBUTE)).toBe(false)
    );
    expect(localStorage.getItem(PALETTE_STORAGE_KEY)).toBeNull();
  });

  it('keeps the cached palette while the read is in flight', () => {
    root.setAttribute(PALETTE_ATTRIBUTE, 'emerald');
    signedIn(true);
    mockFetch.mockReturnValue(new Promise(() => {}));

    renderProvider();

    expect(root.getAttribute(PALETTE_ATTRIBUTE)).toBe('emerald');
  });

  it('does not read the settings for a signed-out visitor', async () => {
    signedIn(false);

    const { findByText } = renderProvider();

    await findByText('app');
    expect(mockFetch).not.toHaveBeenCalled();
  });
});
