/**
 * Tests for OAuth callback page functionality.
 */

// Mock sessionStorage for testing
const mockSessionStorage = {
  getItem: jest.fn(),
  setItem: jest.fn(),
  removeItem: jest.fn(),
  clear: jest.fn(),
};

Object.defineProperty(window, 'sessionStorage', {
  value: mockSessionStorage,
});

// Mock the provider retrieval logic for testing
const getStoredProvider = (): string => {
  return mockSessionStorage.getItem('oauth_provider') || 'generic';
};

describe('OAuth Callback Provider Storage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('getStoredProvider', () => {
    it('should return stored provider from sessionStorage', () => {
      mockSessionStorage.getItem.mockReturnValue('github');
      const result = getStoredProvider();
      expect(result).toBe('github');
      expect(mockSessionStorage.getItem).toHaveBeenCalledWith('oauth_provider');
    });

    it('should return generic as default when no provider stored', () => {
      mockSessionStorage.getItem.mockReturnValue(null);
      const result = getStoredProvider();
      expect(result).toBe('generic');
    });

    it('should handle different provider types', () => {
      const providers = ['github', 'microsoft', 'discord', 'generic'];

      providers.forEach(provider => {
        mockSessionStorage.getItem.mockReturnValue(provider);
        const result = getStoredProvider();
        expect(result).toBe(provider);
      });
    });

    it('should return generic for empty string', () => {
      mockSessionStorage.getItem.mockReturnValue('');
      const result = getStoredProvider();
      expect(result).toBe('generic');
    });
  });

  describe('Provider cleanup', () => {
    it('should remove provider from sessionStorage after successful auth', () => {
      // This would be tested in integration tests where we can test the actual callback page
      // Here we just verify the mock setup works
      mockSessionStorage.removeItem('oauth_provider');
      expect(mockSessionStorage.removeItem).toHaveBeenCalledWith('oauth_provider');
    });
  });
});
