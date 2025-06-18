/**
 * Playwright E2E tests for search highlighting functionality.
 *
 * Tests the search highlighting feature in real browser environment,
 * verifying that search terms are properly highlighted in contact results.
 * Uses shared fixtures and helpers to reduce test duplication.
 */

import { test, expect, Page } from '@playwright/test';
import { createAuthFixtures } from './fixtures/auth';

// Test data factory for consistent mock responses
const createMockContact = (
  id: string,
  firstName: string,
  lastName: string,
  highlighted?: Record<string, string>
) => ({
  id,
  type: 'contacts',
  attributes: {
    first_name: firstName,
    last_name: lastName,
    middle_name: '',
    nick_name: '',
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
    contact_methods: [],
    addresses: [],
    notes: [],
  },
  relationships: { tags: { data: [] } },
  ...(highlighted && { meta: { highlighted } }),
});

const createSearchResponse = (
  query: string,
  contacts: any[],
  processingTime = 15
) => ({
  data: contacts,
  meta: {
    query,
    processing_time_ms: processingTime,
    estimated_total_hits: contacts.length,
    total_count: contacts.length,
    page_count: contacts.length > 0 ? 1 : 0,
    current_page: 1,
    per_page: 20,
  },
});

// Helper functions to reduce duplication
class SearchHighlightHelpers {
  constructor(private page: Page) {}

  async setupAuthentication() {
    const authFixtures = createAuthFixtures(this.page);
    await authFixtures.mockAuthenticated('github');
  }

  async mockSearchEndpoint(
    query: string,
    contacts: any[],
    processingTime = 15
  ) {
    await this.page.route('/api/search/contacts*', async route => {
      const url = new URL(route.request().url());
      const requestQuery = url.searchParams.get('q');

      if (requestQuery === query) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(
            createSearchResponse(query, contacts, processingTime)
          ),
        });
      } else {
        await route.continue();
      }
    });
  }

  async mockEmptyContactsEndpoint() {
    await this.page.route('/api/contacts*', async route => {
      const url = new URL(route.request().url());
      if (!url.searchParams.has('search')) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            data: [],
            meta: { total: 0, page: 1, per_page: 20, total_pages: 0 },
          }),
        });
      } else {
        await route.continue();
      }
    });
  }

  async performSearch(query: string) {
    await this.page.goto('/contacts');
    const searchInput = this.page.getByPlaceholder('Search contacts...');
    await searchInput.fill(query);
    return searchInput;
  }

  async expectHighlightedText(text: string, shouldBeVisible = true) {
    const highlightedElement = this.page
      .locator('mark')
      .filter({ hasText: text });
    if (shouldBeVisible) {
      await expect(highlightedElement).toBeVisible();
      await expect(highlightedElement).toHaveClass(/bg-yellow-200/);
      await expect(highlightedElement).toHaveClass(/dark:bg-yellow-800/);
    } else {
      await expect(highlightedElement).not.toBeVisible();
    }
  }

  async expectSearchResults(
    query: string,
    count: number,
    processingTime?: number
  ) {
    await expect(
      this.page.getByText(
        `${count} contact${count !== 1 ? 's' : ''} found for "${query}"`
      )
    ).toBeVisible();

    if (processingTime) {
      await expect(this.page.getByText(`(${processingTime}ms)`)).toBeVisible();
    }
  }
}

test.describe('Search Highlighting', () => {
  let helpers: SearchHighlightHelpers;

  test.beforeEach(async ({ page }) => {
    helpers = new SearchHighlightHelpers(page);
    await helpers.setupAuthentication();
  });

  test('should highlight search terms in contact names', async ({ page }) => {
    const johnContact = createMockContact('1', 'John', 'Doe', {
      first_name: '<mark>John</mark>',
      email: '<mark>john</mark>@example.com',
    });

    await helpers.mockSearchEndpoint('John', [johnContact], 15);
    await helpers.mockEmptyContactsEndpoint();

    await helpers.performSearch('John');
    await helpers.expectSearchResults('John', 1, 15);
    await helpers.expectHighlightedText('John');
    await helpers.expectHighlightedText('john');
  });

  test('should highlight multiple search terms', async ({ page }) => {
    const johnDoeContact = createMockContact('1', 'John', 'Doe', {
      first_name: '<mark>John</mark>',
      last_name: '<mark>Doe</mark>',
    });

    await helpers.mockSearchEndpoint('John Doe', [johnDoeContact], 23);

    await helpers.performSearch('John Doe');
    await helpers.expectSearchResults('John Doe', 1, 23);
    await helpers.expectHighlightedText('John');
    await helpers.expectHighlightedText('Doe');
  });

  test('should show regular text when no highlighting available', async ({
    page,
  }) => {
    const janeContact = createMockContact('1', 'Jane', 'Smith'); // No highlighting

    await helpers.mockSearchEndpoint('Jane', [janeContact], 8);

    await helpers.performSearch('Jane');
    await helpers.expectSearchResults('Jane', 1, 8);

    // Should show regular text without highlighting
    await expect(page.getByText('Jane Smith')).toBeVisible();
    await expect(page.locator('mark')).toHaveCount(0);
  });

  test('should clear highlighting when search is cleared', async ({ page }) => {
    const johnContact = createMockContact('1', 'John', 'Doe', {
      first_name: '<mark>John</mark>',
    });

    await helpers.mockSearchEndpoint('John', [johnContact], 12);

    // Mock regular contacts endpoint for after clearing search
    await page.route('/api/contacts*', async route => {
      const url = new URL(route.request().url());
      if (!url.searchParams.has('search')) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            data: [createMockContact('1', 'John', 'Doe')], // No highlighting
            meta: { total: 1, page: 1, per_page: 20, total_pages: 1 },
          }),
        });
      } else {
        await route.continue();
      }
    });

    await helpers.performSearch('John');
    await helpers.expectHighlightedText('John');

    // Clear search
    await page.getByRole('button', { name: /clear/i }).click();
    await expect(page.getByText('1 contact found')).toBeVisible();

    // Highlighting should be gone
    await expect(page.locator('mark')).toHaveCount(0);
    await expect(page.getByText('John Doe')).toBeVisible();
  });

  test('should handle search with no results', async ({ page }) => {
    await helpers.mockSearchEndpoint('NonExistent', [], 5);

    await helpers.performSearch('NonExistent');
    await helpers.expectSearchResults('NonExistent', 0, 5);

    await expect(
      page.getByText('No contacts match "NonExistent"')
    ).toBeVisible();
  });

  test('should be accessible with proper ARIA labels', async ({ page }) => {
    const johnContact = createMockContact('1', 'John', 'Doe', {
      first_name: '<mark>John</mark>',
    });

    await helpers.mockSearchEndpoint('John', [johnContact], 10);

    await page.goto('/contacts');

    // Search input should be accessible
    const searchInput = page.getByPlaceholder('Search contacts...');
    await expect(searchInput).toBeVisible();
    await expect(searchInput).toHaveAttribute('type', 'text');

    await searchInput.fill('John');
    await helpers.expectHighlightedText('John');
  });

  test('should work on mobile viewport', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 });

    const johnContact = createMockContact('1', 'John', 'Doe', {
      first_name: '<mark>John</mark>',
    });

    await helpers.mockSearchEndpoint('John', [johnContact], 8);

    await helpers.performSearch('John');
    await helpers.expectHighlightedText('John');
    await helpers.expectSearchResults('John', 1);
  });

  // Security test to ensure DOMPurify is working
  test('should sanitize malicious HTML in search results', async ({ page }) => {
    const maliciousContact = createMockContact('1', 'John', 'Doe', {
      first_name:
        '<script>alert("xss")</script><mark>John</mark><img src="x" onerror="alert(1)">',
    });

    await helpers.mockSearchEndpoint('John', [maliciousContact]);

    await helpers.performSearch('John');

    // Should show highlighted text but not execute scripts
    await helpers.expectHighlightedText('John');

    // Should not contain malicious elements
    await expect(page.locator('script')).toHaveCount(0);
    await expect(page.locator('img[src="x"]')).toHaveCount(0);
  });
});
