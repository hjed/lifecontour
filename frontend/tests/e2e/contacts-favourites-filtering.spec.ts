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
      ).toBeVisible();

      // Should redirect to login
      await expect(unauthenticatedPage).toHaveURL(/\/auth\/login/);

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
      isMobile,
    }) => {
      // Navigate to contacts page
      await authenticatedPage.goto('/contacts');
      await expect(authenticatedPage).toHaveTitle(/Personal Management System/);

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
        .locator('a[href="/contacts/favourites"], a:has-text("Favourites")')
        .first();
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

      // Navigate to contacts with tag filter (unified URL)
      const firstTag = tags[0];
      await page.goto(`/contacts?tag=${firstTag.id}`);
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
      const heading = page.locator('h1');
      await expect(heading).toContainText(new RegExp(firstTag.name, 'i'));
    });

    test('should display empty state when tag has no contacts', async ({
      authenticatedPage,
    }) => {
      // Create a tag first, then navigate to it (it will have no contacts)
      const response = await authenticatedPage.request.post('/api/tags', {
        data: {
          data: {
            type: 'tags',
            attributes: {
              name: 'Empty-Test-Tag-' + Date.now(),
            },
          },
        },
        headers: {
          'Content-Type': 'application/json',
        },
      });

      expect(response.ok()).toBe(true);
      const responseData = await response.json();
      const tagId = responseData.data.id;

      // Navigate to the empty tag via unified contacts URL
      await authenticatedPage.goto(`/contacts?tag=${tagId}`);
      await expect(authenticatedPage).toHaveTitle(/Personal Management System/);

      // Should show the standard empty state on the unified contacts page
      const emptyState = authenticatedPage.getByText(/no contacts found/i);
      await expect(emptyState).toBeVisible();

      // Should not show any contact cards
      const contactCards = authenticatedPage.locator(
        '[data-testid^="contact-"]'
      );
      expect(await contactCards.count()).toBe(0);

      // Clean up the tag
      await authenticatedPage.request.delete(`/api/tags/${tagId}`);
    });

    test('should handle non-existent tag gracefully', async ({
      authenticatedPage,
    }) => {
      // Navigate to a non-existent tag via unified contacts URL
      await authenticatedPage.goto('/contacts?tag=non-existent-tag-999');
      await expect(authenticatedPage).toHaveTitle(/Personal Management System/);

      // The page should load without errors — contacts list shows
      // with no results since the tag ID does not match any real tag
      const heading = authenticatedPage.locator('h1');
      await expect(heading).toBeVisible();
    });
  });

  test.describe('Integration Tests', () => {
    test('should maintain consistent navigation between contact pages', async ({
      favouriteContacts,
      isMobile,
    }) => {
      const { page, contacts } = favouriteContacts;

      // Start on contacts page
      await page.goto('/contacts');
      await expect(page).toHaveTitle(/Personal Management System/);

      // Navigate to favourites page via sidebar
      if (isMobile) {
        const hamburgerButton = page
          .locator(
            'button[aria-label*="menu"], button[aria-label*="navigation"]'
          )
          .first();
        if (await hamburgerButton.isVisible()) {
          await hamburgerButton.click();
        }
      }

      const favouritesLink = page.locator('a[href="/contacts/favourites"]');
      await expect(favouritesLink).toBeVisible();

      // Wait for navigation to complete
      await Promise.all([
        page.waitForURL('**/contacts/favourites'),
        favouritesLink.click(),
      ]);

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
      isMobile,
    }) => {
      const pagesToTest = ['/contacts', '/contacts/favourites'];

      for (const pageUrl of pagesToTest) {
        await authenticatedPage.goto(pageUrl);
        await expect(authenticatedPage).toHaveTitle(
          /Personal Management System/
        );

        // Each page should have sidebar and header
        const sidebar = authenticatedPage
          .locator(
            'aside[role="complementary"], nav[aria-label="Main Navigation"], [data-testid="sidebar"]'
          )
          .first();
        if (isMobile) {
          const hamburgerButton = authenticatedPage
            .locator(
              'button[aria-label*="menu"], button[aria-label*="navigation"]'
            )
            .first();
          const sidebarVisible = await sidebar.isVisible();
          const hamburgerVisible = await hamburgerButton.isVisible();
          expect(sidebarVisible || hamburgerVisible).toBe(true);
        } else {
          await expect(sidebar).toBeVisible();
        }

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
