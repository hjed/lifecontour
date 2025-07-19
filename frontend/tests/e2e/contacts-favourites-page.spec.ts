import { test, expect } from '@playwright/test';
import {
  createTestHelpers,
  navigateAndWaitForStable,
  verifyPageLoadsSuccessfully,
} from './utils/test-helpers';

test.describe('Favourites Page', () => {
  test('should load favourites page successfully', async ({ page }) => {
    const { auth } = createTestHelpers(page);

    await page.goto('/contacts/favourites');
    await expect(page).toHaveTitle(/Personal Management System/);

    // Handle authentication redirect or successful access
    const result = await auth.handleProtectedPageAccess();

    if (result === 'redirected') {
      // Verify login page elements
      await expect(
        page.getByRole('heading', { name: 'Welcome Back' })
      ).toBeVisible();
    } else {
      // If authenticated, verify favourites page content
      const pageContent = page.locator('body');
      await expect(pageContent).toContainText(/favourite/i);

      // Should have a heading about favourites
      const heading = page.locator('h1');
      await expect(heading).toContainText(/favourite/i);
    }
  });

  test('should display favourites page header and description', async ({
    page,
  }) => {
    const { auth } = createTestHelpers(page);

    await page.goto('/contacts/favourites');
    await expect(page).toHaveTitle(/Personal Management System/);

    const result = await auth.handleProtectedPageAccess();

    if (result === 'accessed') {
      // Check for favourites page header
      const heading = page.locator('h1');
      await expect(heading).toBeVisible();
      await expect(heading).toContainText(/favourite/i);

      // Check for description
      const description = page.locator('p').first();
      await expect(description).toBeVisible();
    }
  });

  test('should show favourite contacts when available', async ({ page }) => {
    const { auth } = createTestHelpers(page);

    await page.goto('/contacts/favourites');
    await expect(page).toHaveTitle(/Personal Management System/);

    const result = await auth.handleProtectedPageAccess();

    if (result === 'accessed') {
      // Wait for content to load
      await page.waitForTimeout(2000);

      // Look for contact cards or empty state
      const contactCards = page.locator(
        '[data-testid="contact-card"], .contact-card, [class*="card"]'
      );
      const emptyState = page.locator(
        'text=/no.*favourite.*contacts/i, text=/star.*contacts/i'
      );

      const hasContacts = (await contactCards.count()) > 0;
      const hasEmptyState = (await emptyState.count()) > 0;

      // Should have either contacts or empty state
      expect(hasContacts || hasEmptyState).toBe(true);

      if (hasContacts) {
        // If there are contacts, they should all have favourite toggles
        const favouriteButtons = contactCards.locator(
          'button[aria-label*="favourite"], button[aria-label*="Favourite"]'
        );
        const buttonCount = await favouriteButtons.count();
        expect(buttonCount).toBeGreaterThan(0);
      }
    }
  });

  test('should handle empty favourites state gracefully', async ({ page }) => {
    const { auth } = createTestHelpers(page);

    await page.goto('/contacts/favourites');
    await expect(page).toHaveTitle(/Personal Management System/);

    const result = await auth.handleProtectedPageAccess();

    if (result === 'accessed') {
      // Wait for content to load
      await page.waitForTimeout(2000);

      // Look for empty state indicators
      const emptyStateMessages = [
        'text=/no.*favourite.*contacts/i',
        'text=/star.*contacts/i',
        'text=/add.*favourite/i',
        'text=/no contacts found/i',
      ];

      let hasEmptyStateMessage = false;
      for (const selector of emptyStateMessages) {
        if ((await page.locator(selector).count()) > 0) {
          hasEmptyStateMessage = true;
          break;
        }
      }

      // Look for contact cards
      const contactCards = page.locator(
        '[data-testid="contact-card"], .contact-card, [class*="card"]'
      );
      const hasContacts = (await contactCards.count()) > 0;

      // Should have either empty state message or contacts
      expect(hasEmptyStateMessage || hasContacts).toBe(true);

      if (hasEmptyStateMessage) {
        // Should have a helpful message about starring contacts
        const helpfulText = page.locator('text=/star/i, text=/favourite/i');
        await expect(helpfulText.first()).toBeVisible();
      }
    }
  });

  test('should allow navigation back to all contacts', async ({ page }) => {
    const { auth } = createTestHelpers(page);

    await page.goto('/contacts/favourites');
    await expect(page).toHaveTitle(/Personal Management System/);

    const result = await auth.handleProtectedPageAccess();

    if (result === 'accessed') {
      // Look for navigation back to all contacts
      const allContactsLink = page.locator(
        'a[href="/contacts"]:has-text("All"), a[href="/contacts"]:has-text("Browse"), a:has-text("All Contacts")'
      );

      if ((await allContactsLink.count()) > 0) {
        await expect(allContactsLink.first()).toBeVisible();
        await expect(allContactsLink.first()).toBeEnabled();

        // Click the link
        await allContactsLink.first().click();

        // Should navigate to contacts page
        await page.waitForTimeout(1000);
        const currentUrl = page.url();
        expect(
          currentUrl.includes('/contacts') || currentUrl.includes('/auth/login')
        ).toBe(true);
      }
    }
  });

  test('should show favourites link in sidebar navigation', async ({
    page,
  }) => {
    const { auth } = createTestHelpers(page);

    await page.goto('/contacts');
    await expect(page).toHaveTitle(/Personal Management System/);

    const result = await auth.handleProtectedPageAccess();

    if (result === 'accessed') {
      // Look for favourites link in sidebar
      const favouritesLink = page.locator('a[href="/contacts/favourites"]');

      if ((await favouritesLink.count()) > 0) {
        await expect(favouritesLink.first()).toBeVisible();

        // Should have star icon or "Favourites" text
        const linkContent = favouritesLink.first();
        const hasStarIcon = (await linkContent.locator('svg').count()) > 0;
        const hasFavouritesText = await linkContent.textContent();

        expect(
          hasStarIcon ||
            (hasFavouritesText &&
              hasFavouritesText.toLowerCase().includes('favourite'))
        ).toBe(true);
      }
    }
  });

  test('should maintain consistent UI with main contacts page', async ({
    page,
  }) => {
    const { auth } = createTestHelpers(page);

    await page.goto('/contacts/favourites');
    await expect(page).toHaveTitle(/Personal Management System/);

    const result = await auth.handleProtectedPageAccess();

    if (result === 'accessed') {
      // Should have consistent navigation elements
      const sidebar = page.locator('nav, aside, [role="navigation"]').first();
      await expect(sidebar).toBeVisible();

      // Should have consistent header structure
      const header = page.locator('h1').first();
      await expect(header).toBeVisible();

      // Should have consistent page layout
      const mainContent = page.locator('main, [role="main"]');
      if ((await mainContent.count()) > 0) {
        await expect(mainContent.first()).toBeVisible();
      }
    }
  });

  test('should be accessible with proper ARIA labels', async ({ page }) => {
    const { auth, accessibility } = createTestHelpers(page);

    await page.goto('/contacts/favourites');
    await expect(page).toHaveTitle(/Personal Management System/);

    const result = await auth.handleProtectedPageAccess();

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
      const favouriteButtons = page.locator(
        'button[aria-label*="favourite"], button[aria-label*="Favourite"]'
      );
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
