/**
 * Playwright Fixtures for E2E Tests
 *
 * Provides deterministic test fixtures for authentication, data setup, and cleanup.
 * Eliminates conditional logic and ensures each test has exactly the data it needs.
 *
 * Authentication is handled by the setup project (auth.setup.ts) which saves
 * storageState to a file. All browser projects load this state automatically,
 * so every test starts pre-authenticated — no per-test OAuth overhead.
 *
 * IMPORTANT: This file follows Playwright best practices:
 * - Web-first assertions with auto-retry instead of hard-coded waits
 * - Proper navigation waiting with Promise.all
 * - No waitForTimeout() - use waitForURL, waitForResponse, or assertions instead
 *
 * @see E2E_TESTING_GUIDELINES.md for best practices documentation
 * @see auth.setup.ts for the OAuth setup project
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
export interface TestContact {
  id: string;
  firstName: string;
  lastName: string;
  email?: string;
  phone?: string;
  tags?: string[];
  isFavourite?: boolean;
  importantDates?: Array<{
    date_type: string;
    precision: string;
    year?: number;
    month?: number;
    day?: number;
  }>;
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
  smallDataSet: {
    page: Page;
    contacts: TestContact[];
    tags: Array<{
      id: string;
      name: string;
      attributes?: Record<string, unknown>;
    }>;
  };
  mediumDataSet: {
    page: Page;
    contacts: TestContact[];
    tags: Array<{
      id: string;
      name: string;
      attributes?: Record<string, unknown>;
    }>;
  };
  largeDataSet: {
    page: Page;
    contacts: TestContact[];
    tags: Array<{
      id: string;
      name: string;
      attributes?: Record<string, unknown>;
    }>;
  };
  searchTestData: {
    page: Page;
    contacts: TestContact[];
    tags: Array<{
      id: string;
      name: string;
      attributes?: Record<string, unknown>;
    }>;
  };
  favouritesTestData: {
    page: Page;
    contacts: TestContact[];
    tags: Array<{
      id: string;
      name: string;
      attributes?: Record<string, unknown>;
    }>;
  };
  taggedTestData: {
    page: Page;
    contacts: TestContact[];
    tags: Array<{
      id: string;
      name: string;
      attributes?: Record<string, unknown>;
    }>;
  };
  performanceTestData: {
    page: Page;
    contacts: TestContact[];
    tags: Array<{
      id: string;
      name: string;
      attributes?: Record<string, unknown>;
    }>;
  };

  // Specialized fixtures
  contactsWithoutTags: { page: Page; contacts: TestContact[] };
  favouriteContacts: { page: Page; contacts: TestContact[] };
  regularContacts: { page: Page; contacts: TestContact[] };
  taggedContactsData: {
    page: Page;
    contacts: TestContact[];
    tags: Array<{
      id: string;
      name: string;
      attributes?: Record<string, unknown>;
    }>;
  };

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

// Extend Playwright's base test with our fixtures
// Note: No WorkerFixtures needed — authentication is handled by the setup project
// (auth.setup.ts) via storageState, so every page is pre-authenticated.
export const test = base.extend<TestFixtures>({
  // Test-scoped fixture: Authenticated page
  // The page is already authenticated via storageState from the setup project.
  // No per-test OAuth flow or cookie injection needed.
  authenticatedPage: async ({ page }, use) => {
    await use(page);
  },

  // Test-scoped fixture: Unauthenticated page (clean browser context)
  // Creates a brand-new context WITHOUT storageState so the browser
  // never has auth cookies. This prevents Next.js hydration mismatches
  // that occurred when clearing cookies from an authenticated context
  // (SSR would render authenticated HTML, then the client would see
  // no cookies and try to render unauthenticated UI).
  //
  // We explicitly pass device settings from Playwright's built-in fixtures
  // because browser.newContext() does NOT inherit project `use` config.
  unauthenticatedPage: async (
    { browser, viewport, userAgent, isMobile, hasTouch, deviceScaleFactor },
    use
  ) => {
    const context = await browser.newContext({
      storageState: undefined,
      // Replicate the project's device settings so Mobile Chrome tests
      // still get the correct viewport, touch emulation, etc.
      viewport: viewport ?? undefined,
      userAgent: userAgent ?? undefined,
      isMobile: isMobile ?? undefined,
      hasTouch: hasTouch ?? undefined,
      deviceScaleFactor: deviceScaleFactor ?? undefined,
    });
    const page = await context.newPage();

    await use(page);

    await context.close();
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

    // Calculate relative dates to ensure they appear in the default date chunk (today)
    const today = new Date();
    const yesterday = new Date(today);
    yesterday.setDate(today.getDate() - 1);

    // Create a calendar for the event
    const calendars = await dataManager.createCalendars([
      { name: 'Test Calendar', color: '#3b82f6' },
    ]);
    const calendarId = calendars[0].id;

    // Create test journals via API
    const journals = await dataManager.createJournals([
      {
        title: 'Weekend Hike',
        content: 'Had a great hike in the mountains today.',
        event_date_range: {
          start: yesterday.toISOString(),
          end: yesterday.toISOString(),
        },
        types: ['note'],
      },
      {
        title: 'Team Meeting',
        content: 'Discussed Q1 goals and project timelines.',
        event_date_range: {
          start: today.toISOString(),
          end: today.toISOString(),
        },
        types: ['event'],
        type_data: {
          event: {
            calendar_id: calendarId,
            is_all_day: false,
          },
        },
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
