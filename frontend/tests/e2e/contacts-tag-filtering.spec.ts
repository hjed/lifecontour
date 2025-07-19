import { test, expect } from '@playwright/test';
import { createTestHelpers } from './utils/test-helpers';

test.describe('Tag Filtering Pages', () => {
  test('should load tag filtering page successfully', async ({ page }) => {
    const { auth } = createTestHelpers(page);

    // Test with a sample tag ID
    await page.goto('/contacts/tags/1');
    await expect(page).toHaveTitle(/Personal Management System/);

    // Handle authentication redirect or successful access
    const result = await auth.handleProtectedPageAccess();

    if (result === 'redirected') {
      // Verify login page elements
      await expect(
        page.getByRole('heading', { name: 'Welcome Back' })
      ).toBeVisible();
    } else {
      // If authenticated, verify tag page loads
      await expect(page).toHaveTitle(/Personal Management System/);
    }
  });

  test('should show tag-specific content when tag exists', async ({ page }) => {
    const { auth } = createTestHelpers(page);

    await page.goto('/contacts/tags/1');
    await expect(page).toHaveTitle(/Personal Management System/);

    const result = await auth.handleProtectedPageAccess();

    if (result === 'accessed') {
      // Wait for content to load by waiting for either tag content or error message
      await page.waitForSelector(
        'text=/contacts.*tag/i, text=/tag.*contacts/i, text=/tag.*not.*found/i, text=/not.*found/i, h1',
        { timeout: 10000 }
      );

      // Should show either tag content or "tag not found" message
      const pageContent = page.locator('body');
      const hasTagContent =
        (await pageContent
          .locator('text=/contacts.*tag/i, text=/tag.*contacts/i')
          .count()) > 0;
      const hasNotFoundContent =
        (await pageContent
          .locator('text=/tag.*not.*found/i, text=/not.*found/i')
          .count()) > 0;

      expect(hasTagContent || hasNotFoundContent).toBe(true);

      if (hasTagContent) {
        // Should have a heading with tag information
        const heading = page.locator('h1');
        await expect(heading).toBeVisible();
      }
    }
  });

  test('should handle non-existent tag gracefully', async ({ page }) => {
    const { auth } = createTestHelpers(page);

    // Test with a non-existent tag ID
    await page.goto('/contacts/tags/non-existent-tag-999');
    await expect(page).toHaveTitle(/Personal Management System/);

    const result = await auth.handleProtectedPageAccess();

    if (result === 'accessed') {
      // Wait for content to load by waiting for error messages or page content
      await page.waitForSelector(
        'text=/tag.*not.*found/i, text=/not.*found/i, text=/doesn.*exist/i, text=/invalid.*tag/i, h1, main',
        { timeout: 10000 }
      );

      // Should show "tag not found" or similar error message
      const errorMessages = [
        'text=/tag.*not.*found/i',
        'text=/not.*found/i',
        'text=/doesn.*exist/i',
        'text=/invalid.*tag/i',
      ];

      let hasErrorMessage = false;
      for (const selector of errorMessages) {
        if ((await page.locator(selector).count()) > 0) {
          hasErrorMessage = true;
          break;
        }
      }

      if (hasErrorMessage) {
        // Should have helpful navigation back to contacts
        const backLink = page.locator(
          'a[href="/contacts"], a:has-text("Browse"), a:has-text("All Contacts")'
        );
        if ((await backLink.count()) > 0) {
          await expect(backLink.first()).toBeVisible();
        }
      } else {
        // If no error message, should still be a valid page
        await expect(page).toHaveTitle(/Personal Management System/);
      }
    }
  });

  test('should display contacts filtered by tag when available', async ({
    page,
  }) => {
    const { auth } = createTestHelpers(page);

    await page.goto('/contacts/tags/1');
    await expect(page).toHaveTitle(/Personal Management System/);

    const result = await auth.handleProtectedPageAccess();

    if (result === 'accessed') {
      // Wait for content to load by waiting for contact cards, empty state, or error message
      await page.waitForSelector(
        '[data-testid="contact-card"], .contact-card, [class*="card"], text=/no contacts.*tag/i, text=/no contacts found/i, text=/tag.*not.*found/i',
        { timeout: 10000 }
      );

      // Look for contact cards or empty state
      const contactCards = page.locator(
        '[data-testid="contact-card"], .contact-card, [class*="card"]'
      );
      const emptyState = page.locator(
        'text=/no contacts.*tag/i, text=/no contacts found/i'
      );

      const hasContacts = (await contactCards.count()) > 0;
      const hasEmptyState = (await emptyState.count()) > 0;

      // Should have either contacts or empty state (or tag not found)
      const hasTagNotFound =
        (await page.locator('text=/tag.*not.*found/i').count()) > 0;

      expect(hasContacts || hasEmptyState || hasTagNotFound).toBe(true);

      if (hasContacts) {
        // If there are contacts, they should have favourite toggles
        const favouriteButtons = contactCards.locator(
          'button[aria-label*="favourite"], button[aria-label*="Favourite"]'
        );
        const buttonCount = await favouriteButtons.count();
        expect(buttonCount).toBeGreaterThan(0);

        // Contacts should be clickable
        const contactLinks = contactCards.locator('a[href*="/contacts/"]');
        if ((await contactLinks.count()) > 0) {
          await expect(contactLinks.first()).toBeVisible();
        }
      }
    }
  });

  test('should show tag name in page header when tag exists', async ({
    page,
  }) => {
    const { auth } = createTestHelpers(page);

    await page.goto('/contacts/tags/1');
    await expect(page).toHaveTitle(/Personal Management System/);

    const result = await auth.handleProtectedPageAccess();

    if (result === 'accessed') {
      // Wait for content to load
      await page.waitForTimeout(2000);

      const heading = page.locator('h1');
      await expect(heading).toBeVisible();

      // Should contain tag-related text (either tag name or "not found")
      const headingText = await heading.textContent();
      expect(headingText?.toLowerCase()).toMatch(/(tag|contact|not found)/);
    }
  });

  test('should handle empty tag state with helpful message', async ({
    page,
  }) => {
    const { auth } = createTestHelpers(page);

    await page.goto('/contacts/tags/1');
    await expect(page).toHaveTitle(/Personal Management System/);

    const result = await auth.handleProtectedPageAccess();

    if (result === 'accessed') {
      // Wait for content to load by waiting for empty state, contact cards, or error message
      await page.waitForSelector(
        'text=/no contacts.*tag/i, text=/no contacts found/i, text=/add.*contacts.*tag/i, [data-testid="contact-card"], .contact-card, [class*="card"], text=/tag.*not.*found/i',
        { timeout: 10000 }
      );

      // Look for empty state message
      const emptyStateMessages = [
        'text=/no contacts.*tag/i',
        'text=/no contacts found/i',
        'text=/add.*contacts.*tag/i',
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

      // Look for tag not found
      const hasTagNotFound =
        (await page.locator('text=/tag.*not.*found/i').count()) > 0;

      // Should have one of these states
      expect(hasEmptyStateMessage || hasContacts || hasTagNotFound).toBe(true);
    }
  });

  test('should maintain consistent navigation with other contact pages', async ({
    page,
  }) => {
    const { auth } = createTestHelpers(page);

    await page.goto('/contacts/tags/1');
    await expect(page).toHaveTitle(/Personal Management System/);

    const result = await auth.handleProtectedPageAccess();

    if (result === 'accessed') {
      // Should have consistent navigation elements
      const sidebar = page.locator('nav, aside, [role="navigation"]').first();
      await expect(sidebar).toBeVisible();

      // Should have link back to all contacts
      const allContactsLink = page.locator(
        'a[href="/contacts"]:has-text("All"), a[href="/contacts"]:has-text("Browse")'
      );
      if ((await allContactsLink.count()) > 0) {
        await expect(allContactsLink.first()).toBeVisible();
      }

      // Should have favourites link
      const favouritesLink = page.locator('a[href="/contacts/favourites"]');
      if ((await favouritesLink.count()) > 0) {
        await expect(favouritesLink.first()).toBeVisible();
      }
    }
  });

  test('should show tag icon or indicator in header', async ({ page }) => {
    const { auth } = createTestHelpers(page);

    await page.goto('/contacts/tags/1');
    await expect(page).toHaveTitle(/Personal Management System/);

    const result = await auth.handleProtectedPageAccess();

    if (result === 'accessed') {
      // Wait for content to load by waiting for the heading
      const heading = page.locator('h1');
      await expect(heading).toBeVisible({ timeout: 10000 });

      // Should have tag icon or visual indicator
      const tagIcon = heading.locator('svg');
      if ((await tagIcon.count()) > 0) {
        await expect(tagIcon.first()).toBeVisible();
      }

      // Or should have text indicating this is a tag page
      const headingText = await heading.textContent();
      expect(headingText?.toLowerCase()).toMatch(/(tag|contact|group)/);
    }
  });

  test('should be accessible with proper ARIA structure', async ({ page }) => {
    const { auth } = createTestHelpers(page);

    await page.goto('/contacts/tags/1');
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

      // Check contact links have proper accessibility
      const contactLinks = page.locator('a[href*="/contacts/"]');
      if ((await contactLinks.count()) > 0) {
        const firstLink = contactLinks.first();
        const linkText = await firstLink.textContent();
        expect(linkText).toBeTruthy();
      }
    }
  });
});
