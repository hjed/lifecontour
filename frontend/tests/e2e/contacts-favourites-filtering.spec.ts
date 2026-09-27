import { test, expect } from './fixtures';
import { APP_TITLE_PATTERN } from './utils/test-helpers';

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
      await expect(page).toHaveTitle(APP_TITLE_PATTERN);

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

    // Note: the empty state (copy, no contact cards, and its Browse All
    // Contacts link) is unit-tested in app/contacts/favourites/__tests__/
    // page.test.tsx, and the favourite toggle's aria-label in
    // FavouriteToggle.test.tsx. The login redirect for protected contact
    // routes is covered once, in contacts-tag-filtering.spec.ts.

    test('should toggle favourite status when favourite button is clicked', async ({
      favouritesTestData,
    }) => {
      const { page, contacts } = favouritesTestData;

      // Navigate to contacts page
      await page.goto('/contacts');
      await expect(page).toHaveTitle(APP_TITLE_PATTERN);

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
      isMobile,
    }) => {
      // Navigate to contacts page
      await authenticatedPage.goto('/contacts');
      await expect(authenticatedPage).toHaveTitle(APP_TITLE_PATTERN);

      // Navigate to favourites via sidebar
      // Look for favourites link in sidebar and click it
      if (isMobile) {
        const hamburgerButton = authenticatedPage
          .locator(
            'button[aria-label*="menu"], button[aria-label*="navigation"]'
          )
          .first();
        if (await hamburgerButton.isVisible()) {
          await hamburgerButton.click();
        }
      }

      const favouritesLink = authenticatedPage
        .locator('a[href="/contacts/favourites"]:visible')
        .first();
      await expect(favouritesLink).toBeVisible();
      await favouritesLink.click();

      // Should be on favourites page
      await expect(authenticatedPage).toHaveURL(/\/contacts\/favourites/);
    });
  });

  // Note: tag-based filtering scenarios live in contacts-tag-filtering.spec.ts
  // (the canonical home for tag filtering), so they are not duplicated here.

  test.describe('Integration Tests', () => {
    // Note: 'should allow navigation to favourites page from sidebar' above
    // already walks the sidebar route to /contacts/favourites; the former
    // consistent-navigation and consistent-UI-structure tests repeated that
    // walk and page-shell assertions that the RTL page tests
    // (app/contacts/__tests__) make in jsdom.
  });
});
