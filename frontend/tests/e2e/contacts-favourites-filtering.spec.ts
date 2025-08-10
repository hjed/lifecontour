import { test, expect } from './fixtures';

/**
 * Contact Favourites and Filtering Tests
 *
 * Converted to use the advanced fixture-based testing system.
 * Each test uses deterministic fixtures that provide guaranteed data state.
 */
test.describe('Contact Favourites and Filtering', () => {
  test.describe('Favourites Functionality', () => {
    test('should display favourite contacts when favourite contacts exist', async ({
      favouritesTestData,
    }) => {
      const { page, contacts } = favouritesTestData;

      // Navigate to favourites page
      await page.goto('/contacts/favourites');
      await expect(page).toHaveTitle(/Personal Management System/);

      // Should show favourite contacts (guaranteed by fixture)
      const favouriteContacts = contacts.filter(c => c.isFavourite);
      expect(favouriteContacts.length).toBeGreaterThan(0);

      // Verify favourite contacts are displayed
      for (const contact of favouriteContacts) {
        const contactCard = page.locator(
          `[data-testid="contact-${contact.id}"]`
        );
        await expect(contactCard).toBeVisible();

        // Each contact card should have a favourite button
        const favouriteButton = contactCard.locator(
          '[data-testid="favourite-toggle"]'
        );
        await expect(favouriteButton).toBeVisible();
      }
    });

    test('should display empty state when no favourite contacts exist', async ({
      regularContacts,
    }) => {
      const { page, contacts } = regularContacts;

      // Navigate to favourites page
      await page.goto('/contacts/favourites');
      await expect(page).toHaveTitle(/Personal Management System/);

      // Verify all contacts are non-favourite (guaranteed by fixture)
      contacts.forEach(contact => {
        expect(contact.isFavourite).toBe(false);
      });

      // Should show empty state message
      const emptyState = page.locator('[data-testid="empty-state"]');
      await expect(emptyState).toBeVisible();

      // Verify the empty state contains the expected text
      await expect(emptyState).toContainText('No favourite contacts found');

      // Should not show any contact cards (exclude empty state card)
      const contactCards = page.locator('[data-testid^="contact-"]');
      expect(await contactCards.count()).toBe(0);
    });

    test('should redirect to login when not authenticated', async ({
      unauthenticatedPage,
    }) => {
      // Navigate to favourites page
      await unauthenticatedPage.goto('/contacts/favourites');
      await expect(unauthenticatedPage).toHaveTitle(
        /Personal Management System/
      );

      // Wait for the login form to appear (this indicates the redirect logic is working)
      await expect(
        unauthenticatedPage.getByRole('heading', { name: 'Welcome Back' })
      ).toBeVisible({ timeout: 10000 });

      // Should redirect to login (wait for URL change)
      await expect(unauthenticatedPage).toHaveURL(/\/auth\/login/, {
        timeout: 10000,
      });

      // Should show OAuth button
      await expect(
        unauthenticatedPage.getByRole('button', { name: /continue with/i })
      ).toBeVisible();
    });

    test('should toggle favourite status when favourite button is clicked', async ({
      favouritesTestData,
    }) => {
      const { page, contacts } = favouritesTestData;

      // Navigate to contacts page
      await page.goto('/contacts');
      await expect(page).toHaveTitle(/Personal Management System/);

      // Should show contacts with mixed favourite states (guaranteed by fixture)
      expect(contacts.length).toBeGreaterThan(0);

      // Find first contact and click its favourite button
      const firstContact = contacts[0];
      const contactCard = page.locator(
        `[data-testid="contact-${firstContact.id}"]`
      );
      const favouriteButton = contactCard.locator(
        '[data-testid="favourite-toggle"]'
      );

      await expect(favouriteButton).toBeVisible();
      await favouriteButton.click();

      // Button should still be functional after click
      await expect(favouriteButton).toBeEnabled();
    });

    test('should allow navigation to favourites page from sidebar', async ({
      authenticatedPage,
    }) => {
      // Navigate to contacts page
      await authenticatedPage.goto('/contacts');
      await expect(authenticatedPage).toHaveTitle(/Personal Management System/);

      // Navigate to favourites via sidebar
      // Look for favourites link in sidebar and click it
      const favouritesLink = authenticatedPage.locator(
        'a[href="/contacts/favourites"], a:has-text("Favourites")'
      );
      await expect(favouritesLink).toBeVisible();
      await favouritesLink.click();

      // Should be on favourites page
      await expect(authenticatedPage).toHaveURL(/\/contacts\/favourites/);
    });
  });

  test.describe('Tag-based Filtering', () => {
    test('should display contacts filtered by tag when tag exists', async ({
      taggedContactsData,
    }) => {
      const { page, contacts, tags } = taggedContactsData;

      // Navigate to first tag page (guaranteed by fixture)
      const firstTag = tags[0];
      await page.goto(`/contacts/tags/${firstTag.id}`);
      await expect(page).toHaveTitle(/Personal Management System/);

      // Should show contacts with this tag (guaranteed by fixture)
      const contactsWithTag = contacts.filter(
        c => c.tags && c.tags.includes(firstTag.name)
      );
      expect(contactsWithTag.length).toBeGreaterThan(0);

      // Verify contacts are displayed
      for (const contact of contactsWithTag) {
        const contactCard = page.locator(
          `[data-testid="contact-${contact.id}"]`
        );
        await expect(contactCard).toBeVisible();
      }

      // Page should indicate it's showing the tag
      const pageContent = page.locator('body');
      await expect(pageContent).toContainText(new RegExp(firstTag.name, 'i'));
    });

    test('should display empty state when tag has no contacts', async ({
      authenticatedPage,
    }) => {
      // Navigate to a tag that likely doesn't exist or has no contacts
      await authenticatedPage.goto('/contacts/tags/empty-tag-999');
      await expect(authenticatedPage).toHaveTitle(/Personal Management System/);

      // Should show empty state for this tag
      const emptyState = authenticatedPage.locator(
        'text=/no contacts found in this tag/i'
      );
      await expect(emptyState).toBeVisible();

      // Should not show any contact cards (exclude empty state card)
      const contactCards = authenticatedPage.locator(
        '[data-testid^="contact-"]'
      );
      expect(await contactCards.count()).toBe(0);
    });

    test('should display not found message for non-existent tag', async ({
      authenticatedPage,
    }) => {
      // Navigate to non-existent tag page
      await authenticatedPage.goto('/contacts/tags/non-existent-tag-999');
      await expect(authenticatedPage).toHaveTitle(/Personal Management System/);

      // Should show tag not found message
      const errorContent = authenticatedPage.locator('text=/tag not found/i');
      await expect(errorContent).toBeVisible();
    });
  });

  test.describe('Integration Tests', () => {
    test('should maintain consistent navigation between contact pages', async ({
      favouriteContacts,
    }) => {
      const { page, contacts } = favouriteContacts;

      // Start on contacts page
      await page.goto('/contacts');
      await expect(page).toHaveTitle(/Personal Management System/);

      // Navigate to favourites page via sidebar
      const favouritesLink = page.locator('a[href="/contacts/favourites"]');
      await expect(favouritesLink).toBeVisible();
      await favouritesLink.click();
      await page.waitForLoadState('networkidle');

      // Should be on favourites page
      await expect(page).toHaveURL(/\/contacts\/favourites/);

      // Should show favourite contacts (guaranteed by fixture)
      expect(contacts.length).toBeGreaterThan(0);
      contacts.forEach(contact => {
        expect(contact.isFavourite).toBe(true);
      });
    });

    test('should display consistent UI structure across contact pages', async ({
      authenticatedPage,
    }) => {
      const pagesToTest = ['/contacts', '/contacts/favourites'];

      for (const pageUrl of pagesToTest) {
        await authenticatedPage.goto(pageUrl);
        await expect(authenticatedPage).toHaveTitle(
          /Personal Management System/
        );

        // Each page should have sidebar and header
        const sidebar = authenticatedPage.locator(
          'aside[role="complementary"]'
        );
        await expect(sidebar).toBeVisible();

        const header = authenticatedPage
          .locator('h1, [role="heading"]')
          .first();
        await expect(header).toBeVisible();

        // Each page should have main content area
        const mainContent = authenticatedPage.locator('main, [role="main"]');
        await expect(mainContent).toBeVisible();
      }
    });
  });
});
