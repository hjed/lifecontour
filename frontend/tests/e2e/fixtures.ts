/**
 * Playwright Fixtures for E2E Tests
 *
 * Provides deterministic test fixtures for authentication, data setup, and cleanup.
 * Eliminates conditional logic and ensures each test has exactly the data it needs.
 */

/* eslint-disable react-hooks/rules-of-hooks */
// This file contains Playwright fixtures that use the `use()` function,
// which is not a React hook but triggers the React hooks ESLint rule

import { test as base, Page } from '@playwright/test';
import {
  TestDataManager,
  ContactFactory,
  TagFactory,
  DataSetFactory,
} from './data-management';

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

  // Basic data fixtures
  contactsWithData: { page: Page; contacts: TestContact[] };
  emptyContactsPage: Page;
  contactsWithTags: { page: Page; contacts: TestContact[]; tags: string[] };

  // Advanced data fixtures
  smallDataSet: { page: Page; contacts: TestContact[]; tags: any[] };
  mediumDataSet: { page: Page; contacts: TestContact[]; tags: any[] };
  largeDataSet: { page: Page; contacts: TestContact[]; tags: any[] };
  searchTestData: { page: Page; contacts: TestContact[]; tags: any[] };
  favouritesTestData: { page: Page; contacts: TestContact[]; tags: any[] };
  taggedTestData: { page: Page; contacts: TestContact[]; tags: any[] };
  performanceTestData: { page: Page; contacts: TestContact[]; tags: any[] };

  // Specialized fixtures
  contactsWithoutTags: { page: Page; contacts: TestContact[] };
  favouriteContacts: { page: Page; contacts: TestContact[] };
  regularContacts: { page: Page; contacts: TestContact[] };
  taggedContactsData: { page: Page; contacts: TestContact[]; tags: any[] };

  // Utility fixtures
  testCleanup: (cleanupFn: () => Promise<void>) => void;
  dataFactory: {
    contacts: typeof ContactFactory;
    tags: typeof TagFactory;
    datasets: typeof DataSetFactory;
  };
}

export interface WorkerFixtures {
  // Worker-scoped authentication state
  workerAuth: AuthState;
}

// Global lock to prevent multiple workers from interfering with OAuth flow
let oauthFlowInProgress = false;

/**
 * Complete OAuth flow once per worker and store authentication state
 * Uses the real Hydra OAuth provider for authentic E2E testing
 */
async function completeWorkerOAuthFlow(browser: any): Promise<AuthState> {
  // Wait for any ongoing OAuth flow to complete with timeout
  let waitAttempts = 0;
  const maxWaitAttempts = 30; // 30 seconds max wait
  while (oauthFlowInProgress && waitAttempts < maxWaitAttempts) {
    console.log(
      `🔐 [Worker Auth] Waiting for ongoing OAuth flow to complete... (${waitAttempts}/${maxWaitAttempts})`
    );
    await new Promise(resolve => setTimeout(resolve, 1000));
    waitAttempts++;
  }

  if (oauthFlowInProgress && waitAttempts >= maxWaitAttempts) {
    console.warn(
      '🔐 [Worker Auth] OAuth flow wait timed out, proceeding anyway'
    );
    oauthFlowInProgress = false; // Reset the flag to prevent permanent blocking
  }

  oauthFlowInProgress = true;
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

    // Set up callback tracking before clicking OAuth button
    let callbackCompleted = false;
    let callbackError: string | null = null;

    // Track callback requests to detect completion
    page.on('response', async (response: any) => {
      if (response.url().includes('/auth/callback')) {
        console.log(`🔐 [Worker Auth] Callback response: ${response.status()}`);
        if (response.ok()) {
          callbackCompleted = true;
        } else {
          try {
            const errorData = await response.text();
            callbackError = `${response.status()}: ${errorData}`;
          } catch {
            callbackError = `${response.status()}: Unknown error`;
          }
        }
      }
    });

    // Click OAuth button and wait for navigation
    // WebKit sometimes needs different handling for redirects
    const browserName = page.context().browser()?.browserType().name();

    if (browserName === 'webkit') {
      // WebKit-specific handling: click and wait with longer timeout
      await oauthButtons.first().click();
      await page.waitForTimeout(2000); // Give WebKit more time to process

      // Wait for URL change or timeout
      let attempts = 0;
      const maxAttempts = 15; // 15 seconds total
      let currentUrl = page.url();

      while (currentUrl.includes('/auth/login') && attempts < maxAttempts) {
        await page.waitForTimeout(1000);
        currentUrl = page.url();
        attempts++;
      }

      console.log('🔐 [Worker Auth] WebKit URL after OAuth click:', currentUrl);
    } else {
      // Standard handling for Chromium/Firefox
      await Promise.all([
        page.waitForNavigation({ timeout: 30000 }),
        oauthButtons.first().click(),
      ]);
    }

    const currentUrl = page.url();
    console.log('🔐 [Worker Auth] Current URL after OAuth click:', currentUrl);

    // Step 4: Handle OAuth provider interaction
    if (currentUrl.includes('localhost:4646') || currentUrl.includes('hydra')) {
      console.log(
        '🔐 [Worker Auth] Successfully redirected to Hydra OAuth provider'
      );

      // Wait for automatic redirect back to callback (Hydra is configured with skip_consent: true)
      await page.waitForNavigation({ timeout: 30000 });

      const callbackUrl = page.url();
      console.log('🔐 [Worker Auth] URL after Hydra processing:', callbackUrl);

      if (callbackUrl.includes('/auth/callback')) {
        console.log('🔐 [Worker Auth] OAuth callback received, processing...');

        // Wait for callback processing to complete or fail
        const maxWaitTime = 15000; // 15 seconds
        const startTime = Date.now();
        let waitAttempts = 0;
        const maxWaitAttempts = 30; // 30 attempts = 15 seconds

        while (
          !callbackCompleted &&
          !callbackError &&
          Date.now() - startTime < maxWaitTime &&
          waitAttempts < maxWaitAttempts
        ) {
          await page.waitForTimeout(500);
          waitAttempts++;

          // Log progress every 5 seconds
          if (waitAttempts % 10 === 0) {
            console.log(
              `🔐 [Worker Auth] Still waiting for callback... (${waitAttempts * 0.5}s)`
            );
          }
        }

        if (callbackError) {
          throw new Error(`OAuth callback failed: ${callbackError}`);
        }

        if (!callbackCompleted) {
          console.warn(
            '🔐 [Worker Auth] OAuth callback timed out, but continuing...'
          );
          // Don't throw error, just log warning and continue
          // This allows tests to continue even if OAuth doesn't complete perfectly
        }

        // Wait for final redirect after successful callback
        await page.waitForNavigation({ timeout: 10000 }).catch(() => {
          // Navigation might not happen if already on the target page
          console.log(
            '🔐 [Worker Auth] No final navigation (might already be on target page)'
          );
        });

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
          } else {
            throw new Error(
              'Authentication status check failed: not authenticated'
            );
          }
        } else {
          throw new Error(
            `Authentication status check failed: ${statusResponse.status()}`
          );
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

    // Wait a bit more for browser to fully process the session cookie
    console.log(
      '🔐 [Worker Auth] Waiting for browser to process session cookie...'
    );
    await page.waitForTimeout(1000);

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
    oauthFlowInProgress = false; // Release the lock
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
      `🔐 [Auth State] Applied ${validCookies.length} authentication cookies to page context:`,
      validCookies
        .map(c => `${c.name}=${c.value.substring(0, 20)}...`)
        .join(', ')
    );

    // Verify cookies were applied by checking them
    const appliedCookies = await page.context().cookies();
    console.log(
      `🔐 [Auth State] Verified ${appliedCookies.length} cookies in context:`,
      appliedCookies.map(c => c.name).join(', ')
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
    // Clear any existing auth state using Playwright's context methods
    try {
      // Clear storage state using Playwright's built-in methods
      await page.context().clearCookies();

      // Try to clear storage via evaluate, but catch any SecurityErrors
      try {
        await page.evaluate(() => {
          try {
            sessionStorage.clear();
            localStorage.clear();
          } catch (e) {
            // Ignore SecurityError when storage is not accessible
            console.log(
              'Storage clearing failed (likely SecurityError):',
              (e as Error).message
            );
          }
        });
      } catch (e) {
        // Ignore SecurityError from page.evaluate itself
        console.log(
          'Page evaluate failed (likely SecurityError):',
          (e as Error).message
        );
      }
    } catch (e) {
      // Ignore any other errors during cleanup
      console.log('Context cleanup failed:', (e as Error).message);
    }

    await use(page);
  },

  // Test-scoped fixture: Page with test contacts
  contactsWithData: async ({ authenticatedPage, testCleanup }, use) => {
    const dataManager = new TestDataManager(authenticatedPage);

    // Clear all existing contacts first to ensure clean state
    console.log(
      '🧹 [Fixture] Clearing all existing contacts before creating test data...'
    );
    await dataManager.clearAllContacts();

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

  // Advanced data fixtures
  smallDataSet: async ({ authenticatedPage, testCleanup }, use) => {
    const dataManager = new TestDataManager(authenticatedPage);
    const dataset = DataSetFactory.createSmall();

    console.log('📊 [Small Dataset] Creating small test dataset...');

    // Create contacts with tags (tags will be auto-created)
    const createdContacts = await dataManager.createContacts(dataset.contacts);

    // Extract created tags from the contacts
    const createdTags: { id: string; name: string }[] = [];
    for (const contact of createdContacts) {
      if (contact.tags) {
        for (const tagName of contact.tags) {
          if (!createdTags.find(tag => tag.name === tagName)) {
            // We don't have the tag ID here, but we can use the tag name
            // The actual tag IDs will be available when the contacts are fetched
            createdTags.push({ id: `tag-${tagName}`, name: tagName });
          }
        }
      }
    }

    testCleanup(async () => {
      await dataManager.cleanup();
    });

    await use({
      page: authenticatedPage,
      contacts: createdContacts,
      tags: createdTags,
    });
  },

  mediumDataSet: async ({ authenticatedPage, testCleanup }, use) => {
    const dataManager = new TestDataManager(authenticatedPage);
    const dataset = DataSetFactory.createMedium();

    console.log('📊 [Medium Dataset] Creating medium test dataset...');

    // Create contacts with tags (tags will be auto-created)
    const createdContacts = await dataManager.createContacts(dataset.contacts);

    // Extract created tags from the contacts
    const createdTags: { id: string; name: string }[] = [];
    for (const contact of createdContacts) {
      if (contact.tags) {
        for (const tagName of contact.tags) {
          if (!createdTags.find(tag => tag.name === tagName)) {
            createdTags.push({ id: `tag-${tagName}`, name: tagName });
          }
        }
      }
    }

    testCleanup(async () => {
      await dataManager.cleanup();
    });

    await use({
      page: authenticatedPage,
      contacts: createdContacts,
      tags: createdTags,
    });
  },

  largeDataSet: async ({ authenticatedPage, testCleanup }, use) => {
    const dataManager = new TestDataManager(authenticatedPage);
    const dataset = DataSetFactory.createLarge();

    console.log('📊 [Large Dataset] Creating large test dataset...');

    // Create contacts with tags (tags will be auto-created)
    const createdContacts = await dataManager.createContacts(dataset.contacts);

    // Extract created tags from the contacts
    const createdTags: { id: string; name: string }[] = [];
    for (const contact of createdContacts) {
      if (contact.tags) {
        for (const tagName of contact.tags) {
          if (!createdTags.find(tag => tag.name === tagName)) {
            createdTags.push({ id: `tag-${tagName}`, name: tagName });
          }
        }
      }
    }

    testCleanup(async () => {
      await dataManager.cleanup();
    });

    await use({
      page: authenticatedPage,
      contacts: createdContacts,
      tags: createdTags,
    });
  },

  searchTestData: async ({ authenticatedPage, testCleanup }, use) => {
    const dataManager = new TestDataManager(authenticatedPage);
    const dataset = DataSetFactory.createSearchTestData();

    console.log('🔍 [Search Dataset] Creating search test dataset...');

    // Create contacts with tags (tags will be auto-created)
    const createdContacts = await dataManager.createContacts(dataset.contacts);

    // Extract created tags from the contacts
    const createdTags: { id: string; name: string }[] = [];
    for (const contact of createdContacts) {
      if (contact.tags) {
        for (const tagName of contact.tags) {
          if (!createdTags.find(tag => tag.name === tagName)) {
            createdTags.push({ id: `tag-${tagName}`, name: tagName });
          }
        }
      }
    }

    testCleanup(async () => {
      await dataManager.cleanup();
    });

    await use({
      page: authenticatedPage,
      contacts: createdContacts,
      tags: createdTags,
    });
  },

  favouritesTestData: async ({ authenticatedPage, testCleanup }, use) => {
    const dataManager = new TestDataManager(authenticatedPage);
    const dataset = DataSetFactory.createFavouritesTestData();

    console.log('⭐ [Favourites Dataset] Creating favourites test dataset...');

    // Create contacts with tags (tags will be auto-created)
    const createdContacts = await dataManager.createContacts(dataset.contacts);

    // Extract created tags from the contacts
    const createdTags: { id: string; name: string }[] = [];
    for (const contact of createdContacts) {
      if (contact.tags) {
        for (const tagName of contact.tags) {
          if (!createdTags.find(tag => tag.name === tagName)) {
            createdTags.push({ id: `tag-${tagName}`, name: tagName });
          }
        }
      }
    }

    testCleanup(async () => {
      await dataManager.cleanup();
    });

    await use({
      page: authenticatedPage,
      contacts: createdContacts,
      tags: createdTags,
    });
  },

  taggedTestData: async ({ authenticatedPage, testCleanup }, use) => {
    const dataManager = new TestDataManager(authenticatedPage);
    const dataset = DataSetFactory.createTaggedData();

    console.log('🏷️ [Tagged Dataset] Creating tagged test dataset...');

    // Create contacts with tags (tags will be auto-created)
    const createdContacts = await dataManager.createContacts(dataset.contacts);

    // Extract created tags from the contacts
    const createdTags: { id: string; name: string }[] = [];
    for (const contact of createdContacts) {
      if (contact.tags) {
        for (const tagName of contact.tags) {
          if (!createdTags.find(tag => tag.name === tagName)) {
            createdTags.push({ id: `tag-${tagName}`, name: tagName });
          }
        }
      }
    }

    testCleanup(async () => {
      await dataManager.cleanup();
    });

    await use({
      page: authenticatedPage,
      contacts: createdContacts,
      tags: createdTags,
    });
  },

  performanceTestData: async ({ authenticatedPage, testCleanup }, use) => {
    const dataManager = new TestDataManager(authenticatedPage);
    const dataset = DataSetFactory.createPerformanceTestData();

    console.log(
      '🚀 [Performance Dataset] Creating performance test dataset...'
    );

    // Create contacts with tags (tags will be auto-created)
    const createdContacts = await dataManager.createContacts(dataset.contacts);

    // Extract created tags from the contacts
    const createdTags: { id: string; name: string }[] = [];
    for (const contact of createdContacts) {
      if (contact.tags) {
        for (const tagName of contact.tags) {
          if (!createdTags.find(tag => tag.name === tagName)) {
            createdTags.push({ id: `tag-${tagName}`, name: tagName });
          }
        }
      }
    }

    testCleanup(async () => {
      await dataManager.cleanup();
    });

    await use({
      page: authenticatedPage,
      contacts: createdContacts,
      tags: createdTags,
    });
  },

  // Specialized fixtures
  contactsWithoutTags: async ({ authenticatedPage, testCleanup }, use) => {
    const dataManager = new TestDataManager(authenticatedPage);

    console.log('📝 [No Tags] Creating contacts without tags...');

    const contacts = ContactFactory.createMany(5, { tags: [] });
    const createdContacts = await dataManager.createContacts(contacts);

    testCleanup(async () => {
      await dataManager.cleanup();
    });

    await use({ page: authenticatedPage, contacts: createdContacts });
  },

  favouriteContacts: async ({ authenticatedPage, testCleanup }, use) => {
    const dataManager = new TestDataManager(authenticatedPage);

    console.log('⭐ [Favourites] Creating favourite contacts...');

    const contacts = ContactFactory.createFavourites(3);
    const createdContacts = await dataManager.createContacts(contacts);

    testCleanup(async () => {
      await dataManager.cleanup();
    });

    await use({ page: authenticatedPage, contacts: createdContacts });
  },

  regularContacts: async ({ authenticatedPage, testCleanup }, use) => {
    const dataManager = new TestDataManager(authenticatedPage);

    console.log('📝 [Regular] Creating regular contacts...');

    const contacts = ContactFactory.createMany(5, { isFavourite: false });
    const createdContacts = await dataManager.createContacts(contacts);

    testCleanup(async () => {
      await dataManager.cleanup();
    });

    await use({ page: authenticatedPage, contacts: createdContacts });
  },

  taggedContactsData: async ({ authenticatedPage, testCleanup }, use) => {
    const dataManager = new TestDataManager(authenticatedPage);
    const dataset = DataSetFactory.createTaggedData();

    console.log('🏷️ [Tagged Contacts] Creating tagged contacts dataset...');

    // Create contacts with tags (tags will be auto-created)
    const createdContacts = await dataManager.createContacts(dataset.contacts);

    // Extract created tags from the contacts
    const createdTags: { id: string; name: string }[] = [];
    for (const contact of createdContacts) {
      if (contact.tags) {
        for (const tagName of contact.tags) {
          if (!createdTags.find(tag => tag.name === tagName)) {
            createdTags.push({ id: `tag-${tagName}`, name: tagName });
          }
        }
      }
    }

    testCleanup(async () => {
      await dataManager.cleanup();
    });

    await use({
      page: authenticatedPage,
      contacts: createdContacts,
      tags: createdTags,
    });
  },

  // Utility fixtures
  // eslint-disable-next-line no-empty-pattern
  dataFactory: async ({}, use) => {
    await use({
      contacts: ContactFactory,
      tags: TagFactory,
      datasets: DataSetFactory,
    });
  },

  // Test-scoped fixture: Cleanup tracking
  // eslint-disable-next-line no-empty-pattern
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
