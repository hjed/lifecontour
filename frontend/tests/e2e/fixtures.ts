/**
 * Playwright Fixtures for E2E Tests
 *
 * Provides deterministic test fixtures for authentication, data setup, and cleanup.
 * Eliminates conditional logic and ensures each test has exactly the data it needs.
 */

import { test as base, Page, BrowserContext } from '@playwright/test';
import { createTestHelpers } from './utils/test-helpers';
import { TestDataManager } from './data-management';
import { AuthFixtures, MOCK_USERS } from './fixtures/auth';

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
 */
async function completeWorkerOAuthFlow(browser: any): Promise<AuthState> {
  console.log('🔐 [Worker Auth] Starting OAuth flow for worker...');

  const context = await browser.newContext();
  const page = await context.newPage();

  try {
    // Use the existing auth fixtures to mock authentication
    const authFixtures = new AuthFixtures(page);

    console.log('🔐 [Worker Auth] Setting up mock authentication...');
    await authFixtures.mockAuthenticated('github');

    // Navigate to a protected page to verify authentication works
    await page.goto('http://localhost:3000/contacts');
    await page.waitForLoadState('networkidle');

    // Verify authentication worked by checking auth status
    const statusResponse = await page.request.get('/api/auth/status');
    let isAuthenticated = false;

    if (statusResponse.ok()) {
      const authStatus = await statusResponse.json();
      isAuthenticated = authStatus.authenticated;

      if (isAuthenticated) {
        console.log(
          '🔐 [Worker Auth] Authentication successful:',
          authStatus.user?.email
        );
      }
    }

    // Check if we're on the contacts page (not redirected to login)
    const currentUrl = page.url();
    const onContactsPage =
      currentUrl.includes('/contacts') && !currentUrl.includes('/auth/login');

    if (!isAuthenticated || !onContactsPage) {
      console.warn(
        '🔐 [Worker Auth] Authentication verification failed, but continuing with mock state'
      );
    }

    // Extract authentication state from the browser context
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

    console.log('🔐 [Worker Auth] Authentication state captured successfully');

    return {
      cookies: validCookies,
      sessionData: {
        oauth_provider: 'github',
        oauth_tokens: JSON.stringify({
          access_token: 'test-access-token',
          token_type: 'Bearer',
        }),
        user_session: JSON.stringify(MOCK_USERS.github),
      },
      isAuthenticated: true,
    };
  } catch (error) {
    console.error('🔐 [Worker Auth] OAuth flow failed:', error);

    // Return mock authentication state as fallback
    return {
      cookies: [
        {
          name: 'session_token',
          value: 'test-session-token',
          domain: 'localhost',
          path: '/',
          expires: Math.floor((Date.now() + 3600000) / 1000), // 1 hour in Unix timestamp seconds
          httpOnly: true,
          secure: false,
          sameSite: 'Lax',
        },
      ],
      sessionData: {
        oauth_provider: 'github',
        oauth_tokens: JSON.stringify({
          access_token: 'test-access-token',
          token_type: 'Bearer',
        }),
        user_session: JSON.stringify(MOCK_USERS.github),
      },
      isAuthenticated: true,
    };
  } finally {
    await context.close();
  }
}

/**
 * Apply authentication state to a page context
 */
async function applyAuthState(page: Page, authState: AuthState): Promise<void> {
  // Set up API mocking for authentication
  const authFixtures = new AuthFixtures(page);
  await authFixtures.mockAuthenticated('github');

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

  // Add cookies to the page context
  if (validCookies.length > 0) {
    await page.context().addCookies(validCookies);
    console.log(
      '🔐 [Auth State] Applied authentication cookies and API mocking to page context'
    );
  } else {
    console.log(
      '🔐 [Auth State] Applied API mocking for authentication (no cookies available)'
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
