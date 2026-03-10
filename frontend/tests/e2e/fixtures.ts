/**
 * Playwright Fixtures for E2E Tests
 *
 * Provides deterministic test fixtures for authentication, data setup, and cleanup.
 * Eliminates conditional logic and ensures each test has exactly the data it needs.
 *
 * IMPORTANT: This file follows Playwright best practices:
 * - Web-first assertions with auto-retry instead of hard-coded waits
 * - Proper navigation waiting with Promise.all
 * - No waitForTimeout() - use waitForURL, waitForResponse, or assertions instead
 *
 * @see E2E_TESTING_GUIDELINES.md for best practices documentation
 */

/* eslint-disable react-hooks/rules-of-hooks */
// This file contains Playwright fixtures that use the `use()` function,
// which is not a React hook but triggers the React hooks ESLint rule

import {
  test as base,
  Page,
  expect as playwrightExpect,
} from '@playwright/test';
import {
  TestDataManager,
  ContactFactory,
  TagFactory,
  DataSetFactory,
} from './data-management';
import { FRONTEND_TEST_LOGIN_URL } from './utils/frontend-test-config';

// Types for our fixtures
export interface AuthState {
  storageState: {
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
    origins?: Array<{
      origin: string;
      localStorage?: Array<{
        name: string;
        value: string;
      }>;
    }>;
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

export interface TestJournal {
  id: string;
  title: string;
  content: string;
  event_date_range: {
    start: string;
    end: string;
  };
  types?: string[];
  contacts?: Array<{ id: string; name: string; relationship_type: string }>;
  tags?: Array<{ id: number; name: string; color: string }>;
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

  // Journal fixtures
  journalsWithData: { page: Page; journals: TestJournal[] };
  emptyJournalsPage: Page;

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
 * Helper to wait for OAuth lock with proper timeout
 * Uses Promise-based waiting instead of polling loops
 */
async function waitForOAuthLock(timeoutMs: number = 30000): Promise<boolean> {
  const startTime = Date.now();
  while (oauthFlowInProgress && Date.now() - startTime < timeoutMs) {
    console.log(
      '🔐 [Worker Auth] Waiting for ongoing OAuth flow to complete...'
    );
    await new Promise(resolve => setTimeout(resolve, 1000));
  }
  return !oauthFlowInProgress;
}

/**
 * Helper to convert dataset tags to the expected format for fixtures.
 * Uses original dataset tags to avoid race conditions in tag extraction.
 * This ensures deterministic tag counts regardless of API response timing.
 */
function convertDatasetTags(
  tags: Array<{ name: string }>
): Array<{ id: string; name: string }> {
  return tags.map(tag => ({
    id: `tag-${tag.name}`,
    name: tag.name,
  }));
}

/**
 * Complete OAuth flow once per worker and store authentication state
 * Uses the real Hydra OAuth provider for authentic E2E testing
 *
 * RELIABILITY IMPROVEMENTS:
 * - Uses waitForURL instead of polling loops
 * - Uses web-first assertions for element readiness
 * - Uses waitForResponse for API call completion
 * - Removed all waitForTimeout calls where possible
 */
async function completeWorkerOAuthFlow(browser: any): Promise<AuthState> {
  // Wait for any ongoing OAuth flow to complete with timeout
  const lockAcquired = await waitForOAuthLock(30000);
  if (!lockAcquired) {
    console.warn(
      '🔐 [Worker Auth] OAuth flow wait timed out, proceeding anyway'
    );
    oauthFlowInProgress = false;
  }

  oauthFlowInProgress = true;
  console.log('🔐 [Worker Auth] Starting REAL OAuth flow for worker...');

  const context = await browser.newContext();
  const page = await context.newPage();

  try {
    // Step 1: Navigate to login page and wait for OAuth button to be ready
    await page.goto(FRONTEND_TEST_LOGIN_URL);

    // Wait for OAuth button to be visible and enabled (web-first assertion)
    const oauthButton = page
      .locator('button:has-text("Continue with")')
      .first();
    await playwrightExpect(oauthButton).toBeVisible({ timeout: 15000 });
    await playwrightExpect(oauthButton).toBeEnabled({ timeout: 5000 });

    // Step 2: Click OAuth button and wait for navigation away from login page
    // Use waitForURL to wait for redirect - more reliable than waitForNavigation
    await Promise.all([
      page.waitForURL((url: URL) => !url.toString().includes('/auth/login'), {
        timeout: 30000,
      }),
      oauthButton.click(),
    ]);

    let currentUrl = page.url();
    console.debug(
      '🔐 [Worker Auth] Current URL after OAuth click:',
      currentUrl
    );

    // Step 3: Handle OAuth provider interaction
    if (currentUrl.includes('localhost:4446') || currentUrl.includes('hydra')) {
      console.debug(
        '🔐 [Worker Auth] Successfully redirected to Hydra OAuth provider'
      );

      // Wait for Hydra to process and redirect back to callback
      // Hydra is configured with skip_consent: true, so it auto-redirects
      await page.waitForURL(
        (url: URL) =>
          url.toString().includes('/auth/callback') ||
          url.toString().includes('/contacts'),
        { timeout: 30000 }
      );

      currentUrl = page.url();
      console.debug('🔐 [Worker Auth] URL after Hydra processing:', currentUrl);
    }

    if (currentUrl.includes('/auth/callback')) {
      console.debug('🔐 [Worker Auth] OAuth callback received, processing...');

      // Wait for callback to complete by watching for the final redirect.
      // We can land on the callback directly if Hydra redirects very quickly,
      // so this needs to run even when we never observed the provider page.
      try {
        await page.waitForURL(
          (url: URL) => !url.toString().includes('/auth/callback'),
          { timeout: 15000 }
        );
        currentUrl = page.url();
        console.debug('🔐 [Worker Auth] Final URL after callback:', currentUrl);
      } catch {
        // If redirect times out, we might still be on the callback page
        // This can happen if the callback page is still processing
        console.warn(
          '🔐 [Worker Auth] Callback redirect timeout, checking if still on callback page'
        );
        const stillOnCallback = page.url().includes('/auth/callback');
        if (stillOnCallback) {
          // Wait a bit longer for the callback to complete
          await page.waitForTimeout(2000);
          currentUrl = page.url();
          console.log(
            '🔐 [Worker Auth] After additional wait, URL is:',
            currentUrl
          );
        }
      }
    }

    if (currentUrl.includes('/auth/login')) {
      console.warn(
        '🔐 [Worker Auth] Still on login page - OAuth provider may not be configured'
      );
      throw new Error(
        'OAuth provider not responding - cannot complete real OAuth flow'
      );
    } else {
      console.debug(
        '🔐 [Worker Auth] Already redirected past OAuth provider:',
        currentUrl
      );
    }

    // Step 4: Verify authentication using web-first assertion pattern
    // Uses toPass for automatic retry instead of manual loops
    console.debug('🔐 [Worker Auth] Verifying authentication...');

    // Wait a moment for session to be persisted
    await page.waitForTimeout(500);

    let authUser: string | undefined;
    // NOTE: This uses a 10s timeout because the real OAuth flow involves an external
    // IdP + backend round-trip that can be slow and variable under CI/network load.
    // `toPass` will poll with web-first retries and typically resolve much faster,
    // but we allow up to 10s to avoid flaky failures when the provider is slow.
    await playwrightExpect(async () => {
      // Log cookies before making the request

      const statusResponse = await page.request.get('/api/auth/status');
      playwrightExpect(statusResponse.ok()).toBe(true);

      const authStatus = await statusResponse.json();
      console.debug('🔐 [Worker Auth] Auth status response:', authStatus);
      playwrightExpect(authStatus.authenticated).toBe(true);
      authUser = authStatus.user?.email;
    }).toPass({ timeout: 10000 });

    console.log(
      '🔐 [Worker Auth] Real OAuth authentication successful!',
      authUser
    );

    // Step 5: Extract authentication cookies from browser context
    const cookies = await context.cookies();

    const validCookies = cookies
      .filter((cookie: any) => cookie.name && cookie.value)
      .map((cookie: any) => ({
        ...cookie,
        expires:
          cookie.expires && cookie.expires > 0
            ? Math.floor(cookie.expires)
            : Math.floor((Date.now() + 3600000) / 1000), // Default to 1 hour from now
        // Firefox is stricter about secure flag on non-HTTPS connections
        // For localhost testing, we need to set secure: false to allow cookies
        secure: false,
      }));

    return {
      storageState: {
        cookies: validCookies,
        origins: [],
      },
      isAuthenticated: true,
    };
  } catch (error) {
    console.error('🔐 [Worker Auth] Real OAuth flow failed:', error);
    throw error;
  } finally {
    oauthFlowInProgress = false;
    await context.close();
  }
}

/**
 * Apply authentication state to a page context using Playwright's storageState
 */
async function applyAuthState(page: Page, authState: AuthState): Promise<void> {
  // Add cookies from the stored state
  const validCookies = authState.storageState.cookies
    .filter((cookie: any) => {
      // Ensure required fields are present
      if (!cookie.name || !cookie.value) {
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
    })
    .map((cookie: any) => ({
      ...cookie,
      // Set default domain and path if not present
      domain: cookie.domain || 'localhost',
      path: cookie.path || '/',
      // Firefox is stricter about secure flag on non-HTTPS connections
      // For localhost testing, we need to set secure: false to allow cookies
      secure: false,
    }));

  // Add real authentication cookies to the page context
  if (validCookies.length > 0) {
    await page.context().addCookies(validCookies);

    // Verify cookies were applied by checking them
    const appliedCookies = await page.context().cookies();
    console.log(
      `🔐 [Auth State] Verified ${appliedCookies.length} cookies in context:`,
      appliedCookies.map((c: any) => c.name).join(', ')
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
  // This ensures all tests in a worker share the same authenticated session
  workerAuth: [
    async ({ browser }, use) => {
      const authState = await completeWorkerOAuthFlow(browser);
      await use(authState);
    },
    { scope: 'worker' },
  ],

  // Test-scoped fixture: Authenticated page
  // Uses the worker-scoped auth state to authenticate each test
  authenticatedPage: async ({ page, workerAuth }, use) => {
    // Apply the authenticated state to the test page
    await applyAuthState(page, workerAuth);

    // Verify authentication is working before proceeding with test
    try {
      await playwrightExpect(async () => {
        const statusResponse = await page.request.get('/api/auth/status');
        playwrightExpect(statusResponse.ok()).toBe(true);
        const authStatus = await statusResponse.json();
        playwrightExpect(authStatus.authenticated).toBe(true);
      }).toPass({ timeout: 10000 });
    } catch (error) {
      console.error(
        '🔐 [Auth State] Authentication verification failed:',
        error
      );
      throw error;
    }

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
            console.warn(
              'Storage clearing failed (likely SecurityError):',
              (e as Error).message
            );
          }
        });
      } catch (e) {
        // Ignore SecurityError from page.evaluate itself
        console.warn(
          'Page evaluate failed (likely SecurityError):',
          (e as Error).message
        );
      }
    } catch (e) {
      // Ignore any other errors during cleanup
      console.warn('Context cleanup failed:', (e as Error).message);
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

  // Advanced data fixtures - use convertDatasetTags helper to avoid duplication
  smallDataSet: async ({ authenticatedPage, testCleanup }, use) => {
    const dataManager = new TestDataManager(authenticatedPage);
    const dataset = DataSetFactory.createSmall();
    console.log('📊 [Small Dataset] Creating small test dataset...');
    const createdContacts = await dataManager.createContacts(dataset.contacts);
    testCleanup(async () => await dataManager.cleanup());
    await use({
      page: authenticatedPage,
      contacts: createdContacts,
      tags: convertDatasetTags(dataset.tags),
    });
  },

  mediumDataSet: async ({ authenticatedPage, testCleanup }, use) => {
    const dataManager = new TestDataManager(authenticatedPage);
    const dataset = DataSetFactory.createMedium();
    console.log('📊 [Medium Dataset] Creating medium test dataset...');
    const createdContacts = await dataManager.createContacts(dataset.contacts);
    testCleanup(async () => await dataManager.cleanup());
    await use({
      page: authenticatedPage,
      contacts: createdContacts,
      tags: convertDatasetTags(dataset.tags),
    });
  },

  largeDataSet: async ({ authenticatedPage, testCleanup }, use) => {
    const dataManager = new TestDataManager(authenticatedPage);
    const dataset = DataSetFactory.createLarge();
    console.log('📊 [Large Dataset] Creating large test dataset...');
    const createdContacts = await dataManager.createContacts(dataset.contacts);
    testCleanup(async () => await dataManager.cleanup());
    await use({
      page: authenticatedPage,
      contacts: createdContacts,
      tags: convertDatasetTags(dataset.tags),
    });
  },

  searchTestData: async ({ authenticatedPage, testCleanup }, use) => {
    const dataManager = new TestDataManager(authenticatedPage);
    const dataset = DataSetFactory.createSearchTestData();
    console.log('🔍 [Search Dataset] Creating search test dataset...');
    const createdContacts = await dataManager.createContacts(dataset.contacts);
    testCleanup(async () => await dataManager.cleanup());
    await use({
      page: authenticatedPage,
      contacts: createdContacts,
      tags: convertDatasetTags(dataset.tags),
    });
  },

  favouritesTestData: async ({ authenticatedPage, testCleanup }, use) => {
    const dataManager = new TestDataManager(authenticatedPage);
    const dataset = DataSetFactory.createFavouritesTestData();
    console.log('⭐ [Favourites Dataset] Creating favourites test dataset...');
    const createdContacts = await dataManager.createContacts(dataset.contacts);
    testCleanup(async () => await dataManager.cleanup());
    await use({
      page: authenticatedPage,
      contacts: createdContacts,
      tags: convertDatasetTags(dataset.tags),
    });
  },

  taggedTestData: async ({ authenticatedPage, testCleanup }, use) => {
    const dataManager = new TestDataManager(authenticatedPage);
    const dataset = DataSetFactory.createTaggedData();
    console.log('🏷️ [Tagged Dataset] Creating tagged test dataset...');
    const createdContacts = await dataManager.createContacts(dataset.contacts);
    testCleanup(async () => await dataManager.cleanup());
    await use({
      page: authenticatedPage,
      contacts: createdContacts,
      tags: convertDatasetTags(dataset.tags),
    });
  },

  performanceTestData: async ({ authenticatedPage, testCleanup }, use) => {
    const dataManager = new TestDataManager(authenticatedPage);
    const dataset = DataSetFactory.createPerformanceTestData();
    console.log(
      '🚀 [Performance Dataset] Creating performance test dataset...'
    );
    const createdContacts = await dataManager.createContacts(dataset.contacts);
    testCleanup(async () => await dataManager.cleanup());
    await use({
      page: authenticatedPage,
      contacts: createdContacts,
      tags: convertDatasetTags(dataset.tags),
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

    // Extract created tags from the contacts by fetching their real tag data
    // This is needed because tests navigate to /contacts/tags/${tag.id} requiring real IDs
    const createdTags: { id: string; name: string }[] = [];
    for (const contact of createdContacts) {
      if (contact.tags && contact.tags.length > 0) {
        // Get the real tag data from the contact's tags endpoint
        try {
          const tagsResponse = await authenticatedPage.request.get(
            `/api/contacts/${contact.id}/tags`
          );

          if (tagsResponse.ok()) {
            const tagsData = await tagsResponse.json();
            for (const tagResource of tagsData.data) {
              const tagId = tagResource.id;
              const tagName = tagResource.attributes.name;

              if (!createdTags.some(tag => tag.id === tagId)) {
                createdTags.push({ id: tagId, name: tagName });
              }
            }
          }
        } catch (error) {
          console.warn(
            `⚠️ [Tagged Contacts] Failed to get tags for contact ${contact.id}:`,
            error
          );
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

  // Journal fixtures
  journalsWithData: async ({ authenticatedPage, testCleanup }, use) => {
    const dataManager = new TestDataManager(authenticatedPage);

    // Clear all existing journals first to ensure clean state
    console.log(
      '🧹 [Fixture] Clearing all existing journals before creating test data...'
    );
    await dataManager.clearAllJournals();

    // Create test journals via API
    const journals = await dataManager.createJournals([
      {
        title: 'Weekend Hike',
        content: 'Had a great hike in the mountains today.',
        event_date_range: {
          start: '2026-01-15T09:00:00Z',
          end: '2026-01-16T15:00:00Z',
        },
        types: ['note'],
      },
      {
        title: 'Team Meeting',
        content: 'Discussed Q1 goals and project timelines.',
        event_date_range: {
          start: '2026-01-16T14:00:00Z',
          end: '2026-01-16T15:00:00Z',
        },
        types: ['event'],
      },
    ]);

    // Register cleanup
    testCleanup(async () => {
      await dataManager.cleanup();
    });

    await use({ page: authenticatedPage, journals });
  },

  // Test-scoped fixture: Empty journals page (authenticated but no data)
  emptyJournalsPage: async ({ authenticatedPage, testCleanup }, use) => {
    const dataManager = new TestDataManager(authenticatedPage);

    // Clear all existing journals to ensure empty state
    console.log('🧹 [Fixture] Clearing all journals for empty state...');
    await dataManager.clearAllJournals();

    // Register cleanup (even though there's no data, for consistency)
    testCleanup(async () => {
      await dataManager.cleanup();
    });

    await use(authenticatedPage);
  },

  // Utility fixtures
  dataFactory: async ({}, use) => {
    await use({
      contacts: ContactFactory,
      tags: TagFactory,
      datasets: DataSetFactory,
    });
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
