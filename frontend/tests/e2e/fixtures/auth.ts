/**
 * Authentication fixtures for Playwright e2e tests.
 *
 * Provides mock authentication responses and utilities for testing
 * the OAuth authentication flow without requiring real OAuth providers.
 */

import { Page, Route } from '@playwright/test';

// Mock user data for testing
export const MOCK_USERS = {
  github: {
    id: 'test-user-github',
    email: 'test@example.com',
    name: 'Test User',
    avatar_url: 'https://github.com/test-user.png',
    provider: 'github',
    provider_id: 'github-123',
    created_at: '2024-01-01T00:00:00Z',
    last_login: '2024-01-01T00:00:00Z',
  },
  microsoft: {
    id: 'test-user-microsoft',
    email: 'test@outlook.com',
    name: 'Test User Microsoft',
    avatar_url: 'https://graph.microsoft.com/test-user.png',
    provider: 'microsoft',
    provider_id: 'microsoft-456',
    created_at: '2024-01-01T00:00:00Z',
    last_login: '2024-01-01T00:00:00Z',
  },
  discord: {
    id: 'test-user-discord',
    email: 'test@discord.com',
    name: 'Test User Discord',
    avatar_url: 'https://cdn.discordapp.com/test-user.png',
    provider: 'discord',
    provider_id: 'discord-789',
    created_at: '2024-01-01T00:00:00Z',
    last_login: '2024-01-01T00:00:00Z',
  },
} as const;

// Mock OAuth responses
export const MOCK_OAUTH_RESPONSES = {
  loginSuccess: (provider: keyof typeof MOCK_USERS) => ({
    authorize_url: `https://oauth.${provider}.com/authorize?client_id=test&state=test-state`,
    state: 'test-state',
  }),

  sessionAuthenticated: (provider: keyof typeof MOCK_USERS) => ({
    user: MOCK_USERS[provider],
  }),

  sessionNotAuthenticated: () => ({
    user: null,
  }),

  loginError: () => ({
    errors: [
      {
        code: 'OAUTH_NOT_CONFIGURED',
        detail: 'OAuth provider not configured',
        status: '400',
      },
    ],
  }),

  logoutSuccess: () => ({
    success: true,
  }),
} as const;

// API endpoint patterns for mocking
export const API_PATTERNS = {
  SESSION: '**/api/auth/session',
  LOGIN: '**/api/auth/login',
  LOGOUT: '**/api/auth/logout',
  CALLBACK: '**/api/auth/callback/**',
} as const;

/**
 * Mock authentication API responses for testing.
 */
export class AuthFixtures {
  constructor(private page: Page) {}

  /**
   * Mock session as not authenticated.
   */
  async mockNotAuthenticated(): Promise<void> {
    await this.page.route(API_PATTERNS.SESSION, async (route: Route) => {
      await route.fulfill({
        status: 401,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_OAUTH_RESPONSES.sessionNotAuthenticated()),
      });
    });
  }

  /**
   * Mock session as authenticated with specific provider.
   */
  async mockAuthenticated(provider: keyof typeof MOCK_USERS): Promise<void> {
    await this.page.route(API_PATTERNS.SESSION, async (route: Route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(
          MOCK_OAUTH_RESPONSES.sessionAuthenticated(provider)
        ),
      });
    });
  }

  /**
   * Mock successful OAuth login initiation.
   */
  async mockLoginSuccess(provider: keyof typeof MOCK_USERS): Promise<void> {
    await this.page.route(API_PATTERNS.LOGIN, async (route: Route) => {
      const request = route.request();
      const body = JSON.parse(request.postData() || '{}');

      if (body.provider === provider) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(MOCK_OAUTH_RESPONSES.loginSuccess(provider)),
        });
      } else {
        await route.continue();
      }
    });
  }

  /**
   * Mock OAuth login error.
   */
  async mockLoginError(): Promise<void> {
    await this.page.route(API_PATTERNS.LOGIN, async (route: Route) => {
      await route.fulfill({
        status: 400,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_OAUTH_RESPONSES.loginError()),
      });
    });
  }

  /**
   * Mock successful logout.
   */
  async mockLogoutSuccess(): Promise<void> {
    await this.page.route(API_PATTERNS.LOGOUT, async (route: Route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_OAUTH_RESPONSES.logoutSuccess()),
      });
    });
  }

  /**
   * Clear all authentication-related route mocks.
   */
  async clearMocks(): Promise<void> {
    await this.page.unroute(API_PATTERNS.SESSION);
    await this.page.unroute(API_PATTERNS.LOGIN);
    await this.page.unroute(API_PATTERNS.LOGOUT);
    await this.page.unroute(API_PATTERNS.CALLBACK);
  }

  /**
   * Setup common authentication mocks for login page testing.
   */
  async setupLoginPageMocks(): Promise<void> {
    // Default to not authenticated
    await this.mockNotAuthenticated();
  }
}

/**
 * Create authentication fixtures for a page.
 */
export function createAuthFixtures(page: Page): AuthFixtures {
  return new AuthFixtures(page);
}
