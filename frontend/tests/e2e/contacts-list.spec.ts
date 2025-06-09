/**
 * End-to-end tests for contacts list and search functionality.
 * 
 * Tests contact list display, search capabilities, filtering, and pagination.
 * These tests define the expected behavior for ITER1-004 contact management UI.
 */

import { test, expect } from '@playwright/test';
import { LoginPage } from './pages/login-page';
import { ContactsPage } from './pages/contacts-page';
import { setupApiMocks } from './utils/api-mocks';
import { testContacts, searchTestCases } from './fixtures/test-data';

test.describe('Contacts List and Search', () => {
  let loginPage: LoginPage;
  let contactsPage: ContactsPage;

  test.beforeEach(async ({ page }) => {
    loginPage = new LoginPage(page);
    contactsPage = new ContactsPage(page);
    
    // Set up API mocks for consistent testing
    await setupApiMocks(page);
    
    // Login before each test
    await loginPage.navigateToLogin();
    await loginPage.performOAuthLogin('github');
  });

  test('should display contacts list with proper structure', async () => {
    await contactsPage.navigateToContacts();
    
    // Verify contacts list is visible
    expect(await contactsPage.isContactsListVisible()).toBe(true);
    
    // Verify contacts are displayed
    const contactCount = await contactsPage.getContactCount();
    expect(contactCount).toBeGreaterThan(0);
    
    // Verify first contact details match test data
    const firstContact = await contactsPage.getContactDetails(0);
    expect(firstContact.firstName).toBe(testContacts[0].firstName);
    expect(firstContact.lastName).toBe(testContacts[0].lastName);
    
    // Verify page accessibility
    await contactsPage.verifyContactsPageAccessibility();
  });

  test('should display empty state when no contacts exist', async () => {
    // Mock empty contacts response
    await contactsPage.page.route('**/api/contacts**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          data: [],
          meta: { total: 0, page: 1, limit: 20, total_pages: 0 },
          links: {}
        })
      });
    });

    await contactsPage.navigateToContacts();
    
    // Verify empty state is shown
    expect(await contactsPage.isEmptyStateVisible()).toBe(true);
    
    // Verify empty state message
    const emptyMessage = await contactsPage.getEmptyStateMessage();
    expect(emptyMessage).toContain('No contacts found');
    
    // Verify add contact button is available
    await contactsPage.clickAddContact();
  });

  test('should search contacts successfully', async () => {
    await contactsPage.navigateToContacts();
    
    // Test each search scenario
    for (const testCase of searchTestCases) {
      await contactsPage.searchContacts(testCase.query);
      
      const resultsCount = await contactsPage.getSearchResultsCount();
      
      if (testCase.expectedResults.length > 0) {
        expect(resultsCount).toBeGreaterThan(0);
        
        // Verify search highlighting is present
        expect(await contactsPage.hasSearchHighlighting()).toBe(true);
      } else {
        expect(resultsCount).toBe(0);
      }
      
      // Clear search for next test
      await contactsPage.clearSearch();
    }
  });

  test('should handle search with no results', async () => {
    await contactsPage.navigateToContacts();
    
    // Search for non-existent contact
    await contactsPage.searchContacts('nonexistentcontact');
    
    // Verify no results message
    const resultsCount = await contactsPage.getSearchResultsCount();
    expect(resultsCount).toBe(0);
    
    // Verify empty search state
    expect(await contactsPage.isEmptyStateVisible()).toBe(true);
  });

  test('should filter contacts by tags', async () => {
    await contactsPage.navigateToContacts();
    
    // Apply work tag filter
    await contactsPage.applyTagFilter('work');
    
    // Verify filtered results
    const contactCount = await contactsPage.getContactCount();
    expect(contactCount).toBeGreaterThan(0);
    
    // Verify all displayed contacts have work tag
    // This would need to be implemented based on how tags are displayed
  });

  test('should handle pagination correctly', async () => {
    // Mock large dataset for pagination testing
    await contactsPage.page.route('**/api/contacts**', async (route) => {
      const url = new URL(route.request().url());
      const page = parseInt(url.searchParams.get('page') || '1');
      const limit = parseInt(url.searchParams.get('limit') || '20');
      
      // Create mock data for multiple pages
      const totalContacts = 50;
      const startIndex = (page - 1) * limit;
      const endIndex = Math.min(startIndex + limit, totalContacts);
      
      const pageContacts = [];
      for (let i = startIndex; i < endIndex; i++) {
        pageContacts.push({
          type: 'contact',
          id: (i + 1).toString(),
          attributes: {
            first_name: `Contact${i + 1}`,
            last_name: 'Test',
            email: `contact${i + 1}@example.com`,
            created_at: '2024-01-01T00:00:00Z',
            updated_at: '2024-01-01T00:00:00Z'
          }
        });
      }

      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          data: pageContacts,
          meta: {
            total: totalContacts,
            page,
            limit,
            total_pages: Math.ceil(totalContacts / limit)
          },
          links: {
            self: `/api/contacts?page=${page}&limit=${limit}`,
            first: `/api/contacts?page=1&limit=${limit}`,
            last: `/api/contacts?page=${Math.ceil(totalContacts / limit)}&limit=${limit}`
          }
        })
      });
    });

    await contactsPage.navigateToContacts();
    
    // Verify pagination is visible
    expect(await contactsPage.isPaginationVisible()).toBe(true);
    
    // Test next page navigation
    await contactsPage.goToNextPage();
    
    // Verify we're on page 2
    const contactCount = await contactsPage.getContactCount();
    expect(contactCount).toBeGreaterThan(0);
    
    // Test previous page navigation
    await contactsPage.goToPreviousPage();
    
    // Test direct page navigation
    await contactsPage.goToPage(2);
  });

  test('should show loading states during operations', async () => {
    await contactsPage.navigateToContacts();
    
    // Test search loading state
    await contactsPage.searchContacts('john');
    
    // Loading state should appear briefly
    // Note: This might be too fast to catch in tests, but the UI should support it
    
    // Wait for search to complete
    await contactsPage.waitForContactsToLoad();
    
    // Verify results are shown
    const resultsCount = await contactsPage.getSearchResultsCount();
    expect(resultsCount).toBeGreaterThan(0);
  });

  test('should work responsively on different screen sizes', async () => {
    await contactsPage.navigateToContacts();
    
    // Test responsive contacts list
    await contactsPage.testResponsiveContactsList();
    
    // Test search on mobile
    await contactsPage.setViewportSize(375, 667);
    await contactsPage.searchContacts('john');
    
    const resultsCount = await contactsPage.getSearchResultsCount();
    expect(resultsCount).toBeGreaterThan(0);
  });

  test('should handle API errors gracefully', async () => {
    // Mock API error
    await contactsPage.page.route('**/api/contacts**', async (route) => {
      await route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({
          errors: [{
            status: '500',
            title: 'Internal Server Error',
            detail: 'Failed to fetch contacts'
          }]
        })
      });
    });

    await contactsPage.navigateToContacts();
    
    // Should display error message
    expect(await contactsPage.hasErrorMessage()).toBe(true);
    
    const errorMessage = await contactsPage.getErrorMessage();
    expect(errorMessage).toContain('Failed to fetch contacts');
  });

  test('should handle search API errors gracefully', async () => {
    await contactsPage.navigateToContacts();
    
    // Mock search API error
    await contactsPage.page.route('**/api/search/contacts**', async (route) => {
      await route.fulfill({
        status: 503,
        contentType: 'application/json',
        body: JSON.stringify({
          errors: [{
            status: '503',
            title: 'Search Service Unavailable',
            detail: 'Search service is temporarily unavailable'
          }]
        })
      });
    });

    await contactsPage.searchContacts('john');
    
    // Should display search error message
    expect(await contactsPage.hasErrorMessage()).toBe(true);
    
    const errorMessage = await contactsPage.getErrorMessage();
    expect(errorMessage).toContain('Search service is temporarily unavailable');
  });

  test('should support keyboard navigation', async () => {
    await contactsPage.navigateToContacts();
    
    // Test keyboard navigation in search
    await contactsPage.page.focus('[data-testid="contact-search-input"]');
    await contactsPage.page.keyboard.type('john');
    await contactsPage.page.keyboard.press('Enter');
    
    // Should trigger search
    const resultsCount = await contactsPage.getSearchResultsCount();
    expect(resultsCount).toBeGreaterThan(0);
    
    // Test escape to clear search
    await contactsPage.page.keyboard.press('Escape');
    // Implementation would need to handle this
  });

  test('should display Australian date formats', async () => {
    await contactsPage.navigateToContacts();
    
    // Verify dates are displayed in DD/MM/YYYY format
    // This would need to be implemented based on how dates are shown in the contact list
    const testDate = new Date('2024-01-15');
    await contactsPage.verifyAustralianDateFormat('[data-testid="contact-created-date"]', testDate);
  });
});
