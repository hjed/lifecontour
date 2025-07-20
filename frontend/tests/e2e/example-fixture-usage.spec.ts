/**
 * Example Test File - Demonstrating New Fixture Usage
 *
 * This file shows how to use the new fixture-based testing approach
 * that eliminates conditional logic and provides deterministic test data.
 */

import { test, expect } from './fixtures';

test.describe('Example: Fixture-Based Testing', () => {
  test.describe('Authentication Fixtures', () => {
    test('should access protected page when authenticated', async ({
      authenticatedPage,
    }) => {
      // No conditional logic needed - page is guaranteed to be authenticated
      await authenticatedPage.goto('/contacts');

      // Should be on contacts page, not redirected to login
      await expect(authenticatedPage).toHaveURL(/\/contacts/);
      await expect(authenticatedPage.locator('h1')).toContainText('Contacts');
    });

    test('should redirect to login when unauthenticated', async ({
      unauthenticatedPage,
    }) => {
      // No conditional logic needed - page is guaranteed to be unauthenticated
      await unauthenticatedPage.goto('/contacts');

      // Should be redirected to login page
      await expect(unauthenticatedPage).toHaveURL(/\/auth\/login/);
      await expect(unauthenticatedPage.locator('h1')).toContainText(
        'Welcome Back'
      );
    });
  });

  test.describe('Data Fixtures', () => {
    test('should display contacts when data exists', async ({
      contactsWithData,
    }) => {
      const { page, contacts } = contactsWithData;

      // Navigate to contacts page
      await page.goto('/contacts');

      // Should see the test contacts
      await expect(page.locator('h1')).toContainText('Contacts');

      // Verify specific test contacts are displayed
      for (const contact of contacts) {
        const contactCard = page.locator(
          `[data-testid="contact-${contact.id}"]`
        );
        await expect(contactCard).toBeVisible();
        await expect(contactCard).toContainText(contact.firstName);
        await expect(contactCard).toContainText(contact.lastName);
      }

      // Verify favourite contact is marked correctly
      const favouriteContact = contacts.find(c => c.isFavourite);
      if (favouriteContact) {
        const favouriteCard = page.locator(
          `[data-testid="contact-${favouriteContact.id}"]`
        );
        await expect(
          favouriteCard.locator('[data-testid="favourite-icon"]')
        ).toBeVisible();
      }
    });

    test('should show empty state when no contacts exist', async ({
      emptyContactsPage,
    }) => {
      // Navigate to contacts page
      await emptyContactsPage.goto('/contacts');

      // Should see empty state
      await expect(emptyContactsPage.locator('h1')).toContainText('Contacts');
      await expect(
        emptyContactsPage.locator('[data-testid="empty-state"]')
      ).toBeVisible();
      await expect(
        emptyContactsPage.locator('[data-testid="empty-state"]')
      ).toContainText('No contacts found');
    });

    test('should display contacts with tags correctly', async ({
      contactsWithTags,
    }) => {
      const { page, contacts, tags } = contactsWithTags;

      // Navigate to contacts page
      await page.goto('/contacts');

      // Verify contacts with tags are displayed
      for (const contact of contacts) {
        const contactCard = page.locator(
          `[data-testid="contact-${contact.id}"]`
        );
        await expect(contactCard).toBeVisible();

        // Verify tags are displayed on the contact
        if (contact.tags && contact.tags.length > 0) {
          for (const tagName of contact.tags) {
            const tagElement = contactCard.locator(
              `[data-testid="tag-${tagName}"]`
            );
            await expect(tagElement).toBeVisible();
            await expect(tagElement).toContainText(tagName);
          }
        }
      }

      // Verify tag filter functionality
      for (const tagName of tags) {
        // Click on tag filter
        const tagFilter = page.locator(`[data-testid="tag-filter-${tagName}"]`);
        if (await tagFilter.isVisible()) {
          await tagFilter.click();

          // Should filter contacts to only show those with this tag
          const contactsWithThisTag = contacts.filter(c =>
            c.tags?.includes(tagName)
          );

          for (const contact of contactsWithThisTag) {
            const contactCard = page.locator(
              `[data-testid="contact-${contact.id}"]`
            );
            await expect(contactCard).toBeVisible();
          }

          // Clear filter
          await page.locator('[data-testid="clear-filters"]').click();
        }
      }
    });
  });

  test.describe('Form Interactions', () => {
    test('should create new contact successfully', async ({
      emptyContactsPage,
    }) => {
      // Start with empty state
      await emptyContactsPage.goto('/contacts');

      // Click "Add Contact" button
      await emptyContactsPage
        .locator('[data-testid="add-contact-button"]')
        .click();

      // Should navigate to new contact form
      await expect(emptyContactsPage).toHaveURL(/\/contacts\/new/);

      // Fill out the form
      await emptyContactsPage
        .locator('[data-testid="first-name-input"]')
        .fill('Test');
      await emptyContactsPage
        .locator('[data-testid="last-name-input"]')
        .fill('User');
      await emptyContactsPage
        .locator('[data-testid="email-input"]')
        .fill('test.user@example.com');

      // Submit the form
      await emptyContactsPage
        .locator('[data-testid="save-contact-button"]')
        .click();

      // Should redirect back to contacts list
      await expect(emptyContactsPage).toHaveURL(/\/contacts$/);

      // Should see the new contact
      await expect(
        emptyContactsPage.locator('[data-testid="contact-list"]')
      ).toContainText('Test User');
    });

    test('should edit existing contact', async ({ contactsWithData }) => {
      const { page, contacts } = contactsWithData;

      // Navigate to contacts page
      await page.goto('/contacts');

      // Click on first contact to edit
      const firstContact = contacts[0];
      const contactCard = page.locator(
        `[data-testid="contact-${firstContact.id}"]`
      );
      await contactCard.click();

      // Should navigate to contact detail page
      await expect(page).toHaveURL(new RegExp(`/contacts/${firstContact.id}`));

      // Click edit button
      await page.locator('[data-testid="edit-contact-button"]').click();

      // Should show edit form
      const firstNameInput = page.locator('[data-testid="first-name-input"]');
      await expect(firstNameInput).toHaveValue(firstContact.firstName);

      // Update the name
      await firstNameInput.fill('Updated');

      // Save changes
      await page.locator('[data-testid="save-contact-button"]').click();

      // Should see updated name
      await expect(page.locator('[data-testid="contact-name"]')).toContainText(
        'Updated'
      );
    });
  });

  test.describe('Search and Filtering', () => {
    test('should search contacts by name', async ({ contactsWithData }) => {
      const { page, contacts } = contactsWithData;

      // Navigate to contacts page
      await page.goto('/contacts');

      // Use search functionality
      const searchInput = page.locator('[data-testid="search-input"]');
      await searchInput.fill(contacts[0].firstName);

      // Should filter to show only matching contacts
      const contactCard = page.locator(
        `[data-testid="contact-${contacts[0].id}"]`
      );
      await expect(contactCard).toBeVisible();

      // Other contacts should not be visible
      for (let i = 1; i < contacts.length; i++) {
        const otherContactCard = page.locator(
          `[data-testid="contact-${contacts[i].id}"]`
        );
        await expect(otherContactCard).not.toBeVisible();
      }

      // Clear search
      await searchInput.clear();

      // All contacts should be visible again
      for (const contact of contacts) {
        const contactCard = page.locator(
          `[data-testid="contact-${contact.id}"]`
        );
        await expect(contactCard).toBeVisible();
      }
    });

    test('should filter favourites correctly', async ({ contactsWithData }) => {
      const { page, contacts } = contactsWithData;

      // Navigate to contacts page
      await page.goto('/contacts');

      // Click favourites filter
      await page.locator('[data-testid="favourites-filter"]').click();

      // Should show only favourite contacts
      const favouriteContacts = contacts.filter(c => c.isFavourite);
      const nonFavouriteContacts = contacts.filter(c => !c.isFavourite);

      for (const contact of favouriteContacts) {
        const contactCard = page.locator(
          `[data-testid="contact-${contact.id}"]`
        );
        await expect(contactCard).toBeVisible();
      }

      for (const contact of nonFavouriteContacts) {
        const contactCard = page.locator(
          `[data-testid="contact-${contact.id}"]`
        );
        await expect(contactCard).not.toBeVisible();
      }
    });
  });

  test.describe('Error Handling', () => {
    test('should handle network errors gracefully', async ({
      authenticatedPage,
    }) => {
      // Navigate to contacts page
      await authenticatedPage.goto('/contacts');

      // Simulate network error by intercepting API calls
      await authenticatedPage.route('/api/contacts', route => {
        route.abort('failed');
      });

      // Refresh page to trigger API call
      await authenticatedPage.reload();

      // Should show error state
      await expect(
        authenticatedPage.locator('[data-testid="error-message"]')
      ).toBeVisible();
      await expect(
        authenticatedPage.locator('[data-testid="error-message"]')
      ).toContainText('Failed to load contacts');
    });
  });
});

test.describe('Example: Migration from Old Pattern', () => {
  // This shows how old conditional tests would be migrated to use fixtures

  // OLD WAY (with conditional logic):
  // test('should handle both authenticated and unauthenticated states', async ({ page }) => {
  //   await page.goto('/contacts');
  //   const auth = new AuthHelpers(page);
  //   const result = await auth.handleProtectedPageAccess();
  //
  //   if (result === 'redirected') {
  //     // Test unauthenticated behavior
  //     await expect(page.locator('h1')).toContainText('Welcome Back');
  //   } else {
  //     // Test authenticated behavior
  //     await expect(page.locator('h1')).toContainText('Contacts');
  //   }
  // });

  // NEW WAY (with fixtures - split into separate tests):
  test('authenticated user sees contacts page', async ({
    authenticatedPage,
  }) => {
    await authenticatedPage.goto('/contacts');
    await expect(authenticatedPage.locator('h1')).toContainText('Contacts');
  });

  test('unauthenticated user sees login page', async ({
    unauthenticatedPage,
  }) => {
    await unauthenticatedPage.goto('/contacts');
    await expect(unauthenticatedPage.locator('h1')).toContainText(
      'Welcome Back'
    );
  });
});
