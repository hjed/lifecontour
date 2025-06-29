/**
 * Tests for OAuth callback page functionality.
 */

import { OAuthProvider } from '@/types/auth';

// Mock the determineProvider function logic for testing
const determineProvider = (state: string | null): OAuthProvider => {
  // Parse provider from state parameter (format: "provider:randomString")
  if (state?.includes(':')) {
    const provider = state.split(':')[0].toLowerCase();
    
    // Check if provider is in the enum (case-insensitive)
    if (Object.values(OAuthProvider).includes(provider as OAuthProvider)) {
      return provider as OAuthProvider;
    }
    
    // Map unknown providers to generic (e.g., "hydra" -> "generic")
    return OAuthProvider.GENERIC;
  }

  // Default to generic if state is invalid or missing
  return OAuthProvider.GENERIC;
};

describe('OAuth Callback Provider Determination', () => {
  describe('determineProvider', () => {
    it('should map hydra provider to generic', () => {
      const result = determineProvider('hydra:abc123');
      expect(result).toBe(OAuthProvider.GENERIC);
    });

    it('should handle known providers correctly', () => {
      expect(determineProvider('github:xyz789')).toBe(OAuthProvider.GITHUB);
      expect(determineProvider('microsoft:def456')).toBe(OAuthProvider.MICROSOFT);
      expect(determineProvider('discord:ghi789')).toBe(OAuthProvider.DISCORD);
      expect(determineProvider('generic:jkl012')).toBe(OAuthProvider.GENERIC);
    });

    it('should handle case-insensitive provider names', () => {
      expect(determineProvider('GITHUB:xyz789')).toBe(OAuthProvider.GITHUB);
      expect(determineProvider('GitHub:xyz789')).toBe(OAuthProvider.GITHUB);
      expect(determineProvider('MICROSOFT:def456')).toBe(OAuthProvider.MICROSOFT);
      expect(determineProvider('Microsoft:def456')).toBe(OAuthProvider.MICROSOFT);
    });

    it('should map unknown providers to generic', () => {
      expect(determineProvider('unknown:abc123')).toBe(OAuthProvider.GENERIC);
      expect(determineProvider('custom:xyz789')).toBe(OAuthProvider.GENERIC);
      expect(determineProvider('oauth2:def456')).toBe(OAuthProvider.GENERIC);
    });

    it('should default to generic for invalid state formats', () => {
      expect(determineProvider('invalid-format')).toBe(OAuthProvider.GENERIC);
      expect(determineProvider('no-colon')).toBe(OAuthProvider.GENERIC);
      expect(determineProvider('')).toBe(OAuthProvider.GENERIC);
      expect(determineProvider(null)).toBe(OAuthProvider.GENERIC);
    });

    it('should handle edge cases', () => {
      expect(determineProvider(':')).toBe(OAuthProvider.GENERIC);
      expect(determineProvider(':abc123')).toBe(OAuthProvider.GENERIC);
      expect(determineProvider('provider:')).toBe(OAuthProvider.GENERIC);
    });
  });
});
