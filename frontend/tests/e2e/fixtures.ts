/**
 * Playwright Fixtures for E2E Tests
 *
 * Provides deterministic test fixtures for authentication, data setup, and cleanup.
 * Eliminates conditional logic and ensures each test has exactly the data it needs.
 */

import { test as base, Page, BrowserContext } from '@playwright/test';
import { createTestHelpers } from './utils/test-helpers';
import { TestDataManager } from './data-management';

// Types for our fixtures
export interface AuthState {
  cookies: Array<{
    name: string;
    value: string;
    domain: string;
    path: string;
    expires?: number;
    httpOnly?: boolean;
    secure?: boolean;
    sameSite?: 'Strict' | 'Lax' | 'None';
  }>;
  sessionData: {
    oauth_provider?: string;
    oauth_tokens?: any;
    user_session?: any;
  };
  isAuthenticated: boolean;
}

export interface TestContact {
  id: string;
  firstName: string;
  lastName: string;
  email?: string;
  phone?: string;
  tags?: string[];
  isFavourite?: boolean;
}

export interface TestFixtures {
  // Authentication fixtures
  authenticatedPage: Page;
  unauthenticatedPage: Page;

  // Data fixtures
  contactsWithData: { page: Page; contacts: TestContact[] };
  emptyContactsPage: Page;
  contactsWithTags: { page: Page; contacts: TestContact[]; tags: string[] };

  // Cleanup tracking
  testCleanup: (cleanupFn: () => Promise<void>) => void;
}

export interface WorkerFixtures {
  // Worker-scoped authentication state
  workerAuth: AuthState;
}

/**
 * Complete OAuth flow once per worker and store authentication state
 * Uses the real Hydra OAuth provider for authentic E2E testing
 */
async function completeWorkerOAuthFlow(browser: any): Promise<AuthState> {
  console.log('🔐 [Worker Auth] Starting REAL OAuth flow for worker...');

  const context = await browser.newContext();
  const page = await context.newPage();

  try {
    // Step 1: Navigate to login page
    console.log('🔐 [Worker Auth] Navigating to login page...');
    await page.goto('http://localhost:3000/auth/login');
    await page.waitForLoadState('networkidle');

    // Step 2: Find and click OAuth button
    const oauthButtons = page.locator('button:has-text("Continue with")');
    await oauthButtons.first().waitFor({ timeout: 10000 });

    console.log(
      '🔐 [Worker Auth] Clicking OAuth button to start real OAuth flow...'
    );
    await oauthButtons.first().click();

    // Step 3: Wait for OAuth provider redirect
    await page.waitForTimeout(3000);

    const currentUrl = page.url();
    console.log('🔐 [Worker Auth] Current URL after OAuth click:', currentUrl);

    // Step 4: Handle OAuth provider interaction
    if (currentUrl.includes('localhost:4444') || currentUrl.includes('hydra')) {
      console.log(
        '🔐 [Worker Auth] Successfully redirected to Hydra OAuth provider'
      );

      // The Hydra provider is configured with skip_consent: true, so it should
      // automatically redirect back to our callback without user interaction
      await page.waitForTimeout(2000);

      // Check if we've been redirected back to our callback
      const callbackUrl = page.url();
      console.log('🔐 [Worker Auth] URL after Hydra processing:', callbackUrl);

      if (callbackUrl.includes('/auth/callback')) {
        console.log('🔐 [Worker Auth] OAuth callback received, processing...');

        // Wait for callback processing to complete
        await page.waitForTimeout(5000);

        // Check final URL - should be redirected to a protected page
        const finalUrl = page.url();
        console.log(
          '🔐 [Worker Auth] Final URL after callback processing:',
          finalUrl
        );

        // Verify authentication by checking auth status
        const statusResponse = await page.request.get('/api/auth/status');
        if (statusResponse.ok()) {
          const authStatus = await statusResponse.json();
          if (authStatus.authenticated) {
            console.log(
              '🔐 [Worker Auth] Real OAuth authentication successful!',
              authStatus.user?.email
            );
          }
        }
      }
    } else if (currentUrl.includes('/auth/login')) {
      console.warn(
        '🔐 [Worker Auth] Still on login page - OAuth provider may not be configured properly'
      );
      throw new Error(
        'OAuth provider not responding - cannot complete real OAuth flow'
      );
    } else {
      console.log('🔐 [Worker Auth] Unexpected redirect to:', currentUrl);
    }

    // Extract real authentication state from the browser context
    const cookies = await context.cookies();

    // Filter and validate cookies
    const validCookies = cookies
      .filter((cookie: any) => cookie.name && cookie.value)
      .map((cookie: any) => ({
        ...cookie,
        expires:
          cookie.expires && cookie.expires > 0
            ? Math.floor(cookie.expires)
            : Math.floor((Date.now() + 3600000) / 1000), // Default to 1 hour from now
      }));

    console.log(
      '🔐 [Worker Auth] Real authentication state captured successfully'
    );

    return {
      cookies: validCookies,
      sessionData: {
        // These will be populated from the real OAuth flow
        oauth_provider: 'generic', // The Hydra provider
        oauth_tokens: JSON.stringify({
          access_token: 'real-oauth-token', // This will be set by the real flow
          token_type: 'Bearer',
        }),
        user_session: JSON.stringify({
          id: 'real-user-id', // This will be set by the real flow
          email: 'test@example.com',
          name: 'Test User',
        }),
      },
      isAuthenticated: true,
    };
  } catch (error) {
    console.error('🔐 [Worker Auth] Real OAuth flow failed:', error);
    throw error; // Don't fall back to mocks - fail the test if real OAuth doesn't work
  } finally {
    await context.close();
  }
}

/**
 * Apply authentication state to a page context
 */
async function applyAuthState(page: Page, authState: AuthState): Promise<void> {
  // Filter and validate cookies before adding them
  const validCookies = authState.cookies.filter(cookie => {
    // Ensure required fields are present
    if (!cookie.name || !cookie.value || !cookie.domain || !cookie.path) {
      return false;
    }

    // Validate expires field
    if (
      cookie.expires !== undefined &&
      (cookie.expires < -1 || !Number.isInteger(cookie.expires))
    ) {
      return false;
    }

    return true;
  });

  // Add real authentication cookies to the page context
  if (validCookies.length > 0) {
    await page.context().addCookies(validCookies);
    console.log(
      '🔐 [Auth State] Applied real authentication cookies to page context'
    );
  } else {
    console.warn(
      '🔐 [Auth State] No valid authentication cookies available - authentication may not work'
    );
  }
}

// Extend Playwright's base test with our fixtures
export const test = base.extend<TestFixtures, WorkerFixtures>({
  // Worker-scoped fixture: Complete OAuth flow once per worker
  workerAuth: [
    async ({ browser }, use) => {
      const authState = await completeWorkerOAuthFlow(browser);
      await use(authState);
    },
    { scope: 'worker' },
  ],

  // Test-scoped fixture: Authenticated page
  authenticatedPage: async ({ page, workerAuth }, use) => {
    await applyAuthState(page, workerAuth);
    await use(page);
  },

  // Test-scoped fixture: Unauthenticated page (clean state)
  unauthenticatedPage: async ({ page }, use) => {
    // Clear any existing auth state
    await page.evaluate(() => {
      sessionStorage.clear();
      localStorage.clear();
      // Clear cookies by setting them to expire
      document.cookie.split(';').forEach(cookie => {
        const eqPos = cookie.indexOf('=');
        const name = eqPos > -1 ? cookie.substr(0, eqPos) : cookie;
        document.cookie = `${name}=;expires=Thu, 01 Jan 1970 00:00:00 GMT;path=/`;
      });
    });
    await use(page);
  },

  // Test-scoped fixture: Page with test contacts
  contactsWithData: async ({ authenticatedPage, testCleanup }, use) => {
    const dataManager = new TestDataManager(authenticatedPage);

    // Create test contacts via API
    const contacts = await dataManager.createContacts([
      {
        firstName: 'John',
        lastName: 'Doe',
        email: 'john.doe@example.com',
        phone: '+1234567890',
      },
      {
        firstName: 'Jane',
        lastName: 'Smith',
        email: 'jane.smith@example.com',
        isFavourite: true,
      },
    ]);

    // Set favourite status for Jane
    if (contacts[1]) {
      await dataManager.setContactFavourite(contacts[1].id, true);
    }

    // Register cleanup
    testCleanup(async () => {
      await dataManager.cleanup();
    });

    await use({ page: authenticatedPage, contacts });
  },

  // Test-scoped fixture: Empty contacts page (authenticated but no data)
  emptyContactsPage: async ({ authenticatedPage, testCleanup }, use) => {
    const dataManager = new TestDataManager(authenticatedPage);

    // Clear all existing contacts to ensure empty state
    await dataManager.clearAllContacts();

    // Register cleanup (though there shouldn't be anything to clean up)
    testCleanup(async () => {
      await dataManager.cleanup();
    });

    await use(authenticatedPage);
  },

  // Test-scoped fixture: Contacts with tags
  contactsWithTags: async ({ authenticatedPage, testCleanup }, use) => {
    const dataManager = new TestDataManager(authenticatedPage);

    // Create tags first
    const createdTags = await dataManager.createTags([
      { name: 'work', color: '#3B82F6' },
      { name: 'family', color: '#10B981' },
      { name: 'friends', color: '#F59E0B' },
    ]);

    // Create contacts
    const contacts = await dataManager.createContacts([
      {
        firstName: 'Alice',
        lastName: 'Johnson',
        email: 'alice@work.com',
      },
      {
        firstName: 'Bob',
        lastName: 'Wilson',
        email: 'bob@family.com',
      },
    ]);

    // Assign tags to contacts
    if (contacts[0] && createdTags[0]) {
      await dataManager.assignTagsToContact(contacts[0].id, [
        createdTags[0].id,
      ]);
      contacts[0].tags = ['work'];
    }

    if (contacts[1] && createdTags[1] && createdTags[2]) {
      await dataManager.assignTagsToContact(contacts[1].id, [
        createdTags[1].id,
        createdTags[2].id,
      ]);
      contacts[1].tags = ['family', 'friends'];
    }

    // Register cleanup
    testCleanup(async () => {
      await dataManager.cleanup();
    });

    const tagNames = createdTags.map(tag => tag.name);
    await use({ page: authenticatedPage, contacts, tags: tagNames });
  },

  // Test-scoped fixture: Cleanup tracking
  testCleanup: async ({}, use) => {
    const cleanupTasks: (() => Promise<void>)[] = [];

    const addCleanupTask = (task: () => Promise<void>) => {
      cleanupTasks.push(task);
    };

    await use(addCleanupTask);

    // Execute all cleanup tasks
    console.log(`🧹 [Cleanup] Running ${cleanupTasks.length} cleanup tasks...`);
    for (const task of cleanupTasks) {
      try {
        await task();
      } catch (error) {
        console.warn('🧹 [Cleanup] Task failed:', error);
      }
    }
  },
});

export { expect } from '@playwright/test';
