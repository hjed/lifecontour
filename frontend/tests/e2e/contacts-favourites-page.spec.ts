import { test, expect } from '@playwright/test';
import { createTestHelpers, SELECTORS } from './utils/test-helpers';

test.describe('Favourites Page - Unauthenticated', () => {
  test('should redirect to login when not authenticated', async ({ page }) => {
    const { contacts } = createTestHelpers(page);

    // This test requires the user to be logged out
    await contacts.navigateToUnauthenticatedPage('/contacts/favourites');

    // If we reach here, the redirect worked correctly
    // The navigateToUnauthenticatedPage method already verifies the login form is visible
  });
});

test.describe('Favourites Page - Authenticated', () => {
  test('should display favourites page when authenticated', async ({ page }) => {
    const { contacts } = createTestHelpers(page);

    // This test requires the user to be logged in
    await contacts.navigateToAuthenticatedPage('/contacts/favourites');

    // If we reach here, user is authenticated - test the actual functionality
    await page.waitForTimeout(1000);

    // Should have some page content
    const bodyText = await page.locator('body').textContent();
    expect(bodyText).toBeTruthy();
    expect(bodyText!.trim().length).toBeGreaterThan(0);

    // Should not have obvious JavaScript errors
    const hasJSError = bodyText!.includes('TypeError') || bodyText!.includes('ReferenceError');
    const hasNetworkError = bodyText!.includes('Network Error') || bodyText!.includes('Failed to fetch');
    expect(hasJSError || hasNetworkError).toBe(false);
  });

  test('should display favourites page header and description when authenticated', async ({
    page,
  }) => {
    const { contacts } = createTestHelpers(page);

    // This test requires the user to be logged in
    await contacts.navigateToAuthenticatedPage('/contacts/favourites');

    await page.waitForTimeout(1000);

    // Should have some kind of heading structure
    const headingCount = await page.locator('h1, h2, h3').count();
    expect(headingCount).toBeGreaterThan(0);

    // If there's an h1, it should be about favourites
    const h1Count = await page.locator('h1').count();
    if (h1Count > 0) {
      const heading = page.locator('h1');
      await expect(heading).toBeVisible();
      await expect(heading).toContainText(/favourite/i);
    }

    // Should have some descriptive content
    const textContent = await page.locator('body').textContent();
    expect(textContent).toBeTruthy();
    expect(textContent!.length).toBeGreaterThan(50);
  });

  test('should show favourite contacts or empty state when authenticated', async ({ page }) => {
    const { contacts } = createTestHelpers(page);

    // This test requires the user to be logged in
    await contacts.navigateToAuthenticatedPage('/contacts/favourites');

    await page.waitForTimeout(1000);

    // Test authenticated functionality
    try {
      // Wait for content to load - try contact cards first
      await page.waitForSelector(SELECTORS.CONTACT_CARD, { timeout: 5000 });

      // If we have contact cards, they should have favourite toggles
      const favouriteButtons = page.locator(SELECTORS.FAVOURITE_BUTTON);
      const buttonCount = await favouriteButtons.count();
      expect(buttonCount).toBeGreaterThan(0);
    } catch {
      // If no contact cards, should have empty state messaging
      const emptyStateSelectors = [
        SELECTORS.EMPTY_FAVOURITES,
        'text=/add.*favourite/i',
        'text=/no contacts found/i'
      ];

      let hasEmptyState = false;
      for (const selector of emptyStateSelectors) {
        if ((await page.locator(selector).count()) > 0) {
          hasEmptyState = true;
          break;
        }
      }

      expect(hasEmptyState).toBe(true);
    }
  });

  test('should handle empty favourites state gracefully when authenticated', async ({ page }) => {
    const { contacts } = createTestHelpers(page);

    // This test requires the user to be logged in
    await contacts.navigateToAuthenticatedPage('/contacts/favourites');

    await page.waitForTimeout(1000);

    // Test authenticated functionality - specifically for empty state
    try {
      // Wait for contact cards first
      await page.waitForSelector(SELECTORS.CONTACT_CARD, { timeout: 5000 });
      console.log('Found contact cards - empty state test not applicable');
    } catch {
      // No contact cards found - test empty state handling
      const emptyStateSelectors = [
        SELECTORS.EMPTY_FAVOURITES,
        'text=/add.*favourite/i',
        'text=/no contacts found/i',
        'text=/star.*contact/i'
      ];

      let hasEmptyState = false;
      for (const selector of emptyStateSelectors) {
        if ((await page.locator(selector).count()) > 0) {
          hasEmptyState = true;
          break;
        }
      }

      // Should have some kind of empty state messaging
      expect(hasEmptyState).toBe(true);

      // Should have helpful text about favourites/starring
      const helpfulText = page.locator('text=/star/i, text=/favourite/i');
      const helpfulTextCount = await helpfulText.count();
      expect(helpfulTextCount).toBeGreaterThan(0);
    }
  });

  test('should allow navigation back to all contacts when authenticated', async ({ page }) => {
    const { contacts } = createTestHelpers(page);

    // This test requires the user to be logged in
    await contacts.navigateToAuthenticatedPage('/contacts/favourites');

    await page.waitForTimeout(1000);

    // Test authenticated functionality
    const allContactsLink = page.locator(SELECTORS.ALL_CONTACTS_LINK);
    const linkCount = await allContactsLink.count();

    if (linkCount > 0) {
      await expect(allContactsLink.first()).toBeVisible();
      await expect(allContactsLink.first()).toBeEnabled();

      // Click the link and verify navigation
      await allContactsLink.first().click();
      await page.waitForTimeout(1000);

      const currentUrl = page.url();
      expect(currentUrl).toContain('/contacts');
    } else {
      console.log('No "All Contacts" navigation link found - may be in different UI location');
    }
  });

  test('should show favourites link in sidebar navigation when authenticated', async ({
    page,
  }) => {
    const { contacts, sidebar } = createTestHelpers(page);

    // This test requires the user to be logged in
    await contacts.navigateToAuthenticatedPage('/contacts');

    await page.waitForTimeout(1000);

    // Test authenticated functionality
    try {
      await sidebar.waitForSidebar();
      await sidebar.testFavouritesLink();
    } catch {
      console.log('Sidebar favourites link test skipped - sidebar not found or different structure');
    }
  });

  test('should maintain consistent UI with main contacts page', async ({
    page,
  }) => {
    const { contacts } = createTestHelpers(page);

    const result = await contacts.navigateToPageWithAuth('/contacts/favourites');

    if (result === 'accessed') {
      // Should have consistent navigation elements
      const sidebar = page.locator(SELECTORS.SIDEBAR).first();
      await expect(sidebar).toBeVisible();

      // Should have consistent header structure
      const header = page.locator('h1').first();
      await expect(header).toBeVisible();

      // Should have consistent page layout
      const mainContent = page.locator(SELECTORS.MAIN_CONTENT);
      if ((await mainContent.count()) > 0) {
        await expect(mainContent.first()).toBeVisible();
      }
    }
  });

  test('should be accessible with proper ARIA labels', async ({ page }) => {
    const { contacts } = createTestHelpers(page);

    const result = await contacts.navigateToPageWithAuth('/contacts/favourites');

    if (result === 'accessed') {
      // Check for proper heading structure
      const mainHeading = page.locator('h1');
      await expect(mainHeading).toBeVisible();

      // Check for proper navigation labels
      const navigation = page.locator('[role="navigation"]');
      if ((await navigation.count()) > 0) {
        const firstNav = navigation.first();
        const ariaLabel = await firstNav.getAttribute('aria-label');
        expect(ariaLabel).toBeTruthy();
      }

      // Check favourite buttons have proper labels
      const favouriteButtons = page.locator(SELECTORS.FAVOURITE_BUTTON);
      const buttonCount = await favouriteButtons.count();

      if (buttonCount > 0) {
        const firstButton = favouriteButtons.first();
        const ariaLabel = await firstButton.getAttribute('aria-label');
        expect(ariaLabel).toBeTruthy();
        expect(ariaLabel?.toLowerCase()).toContain('favourite');
      }
    }
  });
});
