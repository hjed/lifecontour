/**
 * End-to-end tests for global search functionality.
 * 
 * Tests global search component, search across entity types, and search suggestions.
 * These tests define the expected behavior for ITER1-004 global search UI.
 */

import { test, expect } from '@playwright/test';
import { LoginPage } from './pages/login-page';
import { setupApiMocks } from './utils/api-mocks';

test.describe('Global Search', () => {
  let loginPage: LoginPage;

  // Global search selectors
  const selectors = {
    globalSearchInput: '[data-testid="global-search-input"]',
    globalSearchButton: '[data-testid="global-search-button"]',
    searchResults: '[data-testid="global-search-results"]',
    searchResultItem: '[data-testid^="global-search-result-"]',
    searchSuggestions: '[data-testid="search-suggestions"]',
    suggestionItem: '[data-testid^="suggestion-"]',
    searchFilters: '[data-testid="search-filters"]',
    entityTypeFilter: '[data-testid^="entity-filter-"]',
    searchHighlight: '[data-testid="search-highlight"]',
    noResults: '[data-testid="no-search-results"]',
    searchLoading: '[data-testid="global-search-loading"]',
    clearSearchButton: '[data-testid="clear-global-search"]'
  };

  test.beforeEach(async ({ page }) => {
    loginPage = new LoginPage(page);
    
    // Set up API mocks for consistent testing
    await setupApiMocks(page);
    
    // Login before each test
    await loginPage.navigateToLogin();
    await loginPage.performOAuthLogin('github');
    
    // Navigate to home page where global search should be available
    await page.goto('/');
  });

  test('should display global search component in header', async ({ page }) => {
    // Verify global search input is visible
    expect(await page.isVisible(selectors.globalSearchInput)).toBe(true);
    
    // Verify search input has proper placeholder
    const placeholder = await page.getAttribute(selectors.globalSearchInput, 'placeholder');
    expect(placeholder).toContain('Search');
    
    // Verify search button is visible
    expect(await page.isVisible(selectors.globalSearchButton)).toBe(true);
  });

  test('should perform global search across entity types', async ({ page }) => {
    // Type search query
    await page.fill(selectors.globalSearchInput, 'john');
    await page.click(selectors.globalSearchButton);
    
    // Wait for search results
    await page.waitForResponse('**/api/search/global**');
    
    // Verify search results are displayed
    expect(await page.isVisible(selectors.searchResults)).toBe(true);
    
    // Verify results contain contacts
    const resultItems = await page.locator(selectors.searchResultItem).count();
    expect(resultItems).toBeGreaterThan(0);
    
    // Verify search highlighting is present
    expect(await page.isVisible(selectors.searchHighlight)).toBe(true);
  });

  test('should show search suggestions while typing', async ({ page }) => {
    // Mock search suggestions endpoint
    await page.route('**/api/search/suggestions**', async (route) => {
      const url = new URL(route.request().url());
      const query = url.searchParams.get('q') || '';
      
      const suggestions = [
        'john smith',
        'john doe',
        'johnson company'
      ].filter(s => s.includes(query.toLowerCase()));

      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          suggestions: suggestions.slice(0, 5)
        })
      });
    });

    // Start typing in search input
    await page.fill(selectors.globalSearchInput, 'joh');
    
    // Wait for suggestions to appear
    await page.waitForResponse('**/api/search/suggestions**');
    
    // Verify suggestions are displayed
    expect(await page.isVisible(selectors.searchSuggestions)).toBe(true);
    
    // Verify suggestion items are present
    const suggestionCount = await page.locator(selectors.suggestionItem).count();
    expect(suggestionCount).toBeGreaterThan(0);
    
    // Click on a suggestion
    await page.click(`${selectors.suggestionItem}:first-child`);
    
    // Should trigger search with selected suggestion
    await page.waitForResponse('**/api/search/global**');
    expect(await page.isVisible(selectors.searchResults)).toBe(true);
  });

  test('should filter search results by entity type', async ({ page }) => {
    // Perform initial search
    await page.fill(selectors.globalSearchInput, 'test');
    await page.click(selectors.globalSearchButton);
    
    // Wait for search results
    await page.waitForResponse('**/api/search/global**');
    
    // Verify filters are available
    expect(await page.isVisible(selectors.searchFilters)).toBe(true);
    
    // Apply contacts filter
    await page.click('[data-testid="entity-filter-contacts"]');
    
    // Should filter results to only show contacts
    await page.waitForResponse('**/api/search/global**');
    
    // Verify filtered results
    const resultItems = await page.locator(selectors.searchResultItem).all();
    for (const item of resultItems) {
      const entityType = await item.getAttribute('data-entity-type');
      expect(entityType).toBe('contact');
    }
  });

  test('should handle empty search results', async ({ page }) => {
    // Search for non-existent term
    await page.fill(selectors.globalSearchInput, 'nonexistentterm123');
    await page.click(selectors.globalSearchButton);
    
    // Wait for search response
    await page.waitForResponse('**/api/search/global**');
    
    // Verify no results message is displayed
    expect(await page.isVisible(selectors.noResults)).toBe(true);
    
    // Verify message content
    const noResultsText = await page.textContent(selectors.noResults);
    expect(noResultsText).toContain('No results found');
  });

  test('should clear search results', async ({ page }) => {
    // Perform search
    await page.fill(selectors.globalSearchInput, 'john');
    await page.click(selectors.globalSearchButton);
    
    // Wait for results
    await page.waitForResponse('**/api/search/global**');
    expect(await page.isVisible(selectors.searchResults)).toBe(true);
    
    // Clear search
    await page.click(selectors.clearSearchButton);
    
    // Verify search is cleared
    const searchValue = await page.inputValue(selectors.globalSearchInput);
    expect(searchValue).toBe('');
    
    // Verify results are hidden
    expect(await page.isVisible(selectors.searchResults)).toBe(false);
  });

  test('should support keyboard navigation', async ({ page }) => {
    // Focus search input
    await page.focus(selectors.globalSearchInput);
    
    // Type search query
    await page.keyboard.type('john');
    
    // Press Enter to search
    await page.keyboard.press('Enter');
    
    // Should trigger search
    await page.waitForResponse('**/api/search/global**');
    expect(await page.isVisible(selectors.searchResults)).toBe(true);
    
    // Test arrow key navigation through results
    await page.keyboard.press('ArrowDown');
    await page.keyboard.press('ArrowDown');
    await page.keyboard.press('Enter');
    
    // Should navigate to selected result
    // Implementation would depend on specific behavior
  });

  test('should work on mobile devices', async ({ page }) => {
    // Set mobile viewport
    await page.setViewportSize({ width: 375, height: 667 });
    
    // Global search should still be accessible
    expect(await page.isVisible(selectors.globalSearchInput)).toBe(true);
    
    // Perform search on mobile
    await page.fill(selectors.globalSearchInput, 'john');
    await page.click(selectors.globalSearchButton);
    
    // Wait for results
    await page.waitForResponse('**/api/search/global**');
    
    // Results should be displayed properly on mobile
    expect(await page.isVisible(selectors.searchResults)).toBe(true);
    
    // Results should be responsive
    const resultsContainer = page.locator(selectors.searchResults);
    const boundingBox = await resultsContainer.boundingBox();
    expect(boundingBox?.width).toBeLessThanOrEqual(375);
  });

  test('should handle search API errors gracefully', async ({ page }) => {
    // Mock search API error
    await page.route('**/api/search/global**', async (route) => {
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

    // Perform search
    await page.fill(selectors.globalSearchInput, 'john');
    await page.click(selectors.globalSearchButton);
    
    // Should display error message
    const errorMessage = await page.textContent('[data-testid="error-message"]');
    expect(errorMessage).toContain('Search service is temporarily unavailable');
  });

  test('should show loading state during search', async ({ page }) => {
    // Perform search
    await page.fill(selectors.globalSearchInput, 'john');
    await page.click(selectors.globalSearchButton);
    
    // Loading state should appear briefly
    // Note: This might be too fast to catch reliably in tests
    
    // Wait for search to complete
    await page.waitForResponse('**/api/search/global**');
    
    // Loading should be hidden
    expect(await page.isVisible(selectors.searchLoading)).toBe(false);
    
    // Results should be visible
    expect(await page.isVisible(selectors.searchResults)).toBe(true);
  });

  test('should support typo tolerance in search', async ({ page }) => {
    // Search with typo
    await page.fill(selectors.globalSearchInput, 'jhon'); // typo for 'john'
    await page.click(selectors.globalSearchButton);
    
    // Wait for search results
    await page.waitForResponse('**/api/search/global**');
    
    // Should still return results for 'john'
    expect(await page.isVisible(selectors.searchResults)).toBe(true);
    
    const resultItems = await page.locator(selectors.searchResultItem).count();
    expect(resultItems).toBeGreaterThan(0);
  });

  test('should navigate to detailed results from global search', async ({ page }) => {
    // Perform search
    await page.fill(selectors.globalSearchInput, 'john');
    await page.click(selectors.globalSearchButton);
    
    // Wait for results
    await page.waitForResponse('**/api/search/global**');
    
    // Click on first contact result
    await page.click(`${selectors.searchResultItem}[data-entity-type="contact"]:first-child`);
    
    // Should navigate to contact details or contacts page
    await page.waitForURL('**/contacts/**');
    
    // Verify we're on the correct page
    expect(page.url()).toMatch(/\/contacts/);
  });

  test('should verify search accessibility', async ({ page }) => {
    // Check search input has proper ARIA attributes
    const searchInput = page.locator(selectors.globalSearchInput);
    await expect(searchInput).toHaveAttribute('role', 'searchbox');
    await expect(searchInput).toHaveAttribute('aria-label');
    
    // Check search button has proper label
    const searchButton = page.locator(selectors.globalSearchButton);
    await expect(searchButton).toHaveAttribute('aria-label');
    
    // Perform search to test results accessibility
    await page.fill(selectors.globalSearchInput, 'john');
    await page.click(selectors.globalSearchButton);
    
    await page.waitForResponse('**/api/search/global**');
    
    // Check search results have proper ARIA attributes
    const resultsContainer = page.locator(selectors.searchResults);
    await expect(resultsContainer).toHaveAttribute('role', 'region');
    await expect(resultsContainer).toHaveAttribute('aria-label');
    
    // Check individual result items have proper roles
    const resultItems = await page.locator(selectors.searchResultItem).all();
    for (const item of resultItems) {
      const role = await item.getAttribute('role');
      expect(role).toBeTruthy();
    }
  });
});
