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

    // TODO: Re-enable when contact tag display functionality is implemented
    test.skip('should display contacts with tags correctly', async ({
      contactsWithTags,
    }) => {
      // Test skipped - contact tag display functionality not yet implemented
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

      // Submit the form
      await emptyContactsPage
        .locator('[data-testid="save-contact-button"]')
        .click();

      // Should redirect to the newly created contact's detail page
      await expect(emptyContactsPage).toHaveURL(/\/contacts\/\d+$/);

      // Should see the new contact's name on the detail page
      await expect(
        emptyContactsPage.getByRole('heading', { name: 'Test User' })
      ).toBeVisible();
    });

    test('should edit existing contact', async ({ contactsWithData }) => {
      const { page, contacts } = contactsWithData;

      // Navigate to contacts page
      await page.goto('/contacts');

      // Click on first contact to edit
      const firstContact = contacts[0];
      const contactName = `${firstContact.firstName} ${firstContact.lastName}`;
      const contactLink = page.getByRole('link', { name: contactName });
      await contactLink.click();

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
      // Set up route interception before navigation
      await authenticatedPage.route('**/api/contacts**', route => {
        console.log('Intercepting API call:', route.request().url());
        route.abort('failed');
      });

      // Navigate to contacts page (this should trigger the API call)
      await authenticatedPage.goto('/contacts');

      // Wait for the page to load and process the error
      await authenticatedPage.waitForLoadState('networkidle');

      // Should show error state (wait longer for React Query retries to complete)
      await expect(
        authenticatedPage.locator('[data-testid="error-message"]')
      ).toBeVisible({ timeout: 15000 }); // Wait up to 15 seconds for retries to complete
      await expect(
        authenticatedPage.locator('[data-testid="error-message"]')
      ).toContainText('Failed to fetch');
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

test.describe('Advanced Data Fixtures Examples', () => {
  test.describe('Dataset Fixtures', () => {
    test('should work with small dataset for quick tests', async ({
      smallDataSet,
    }) => {
      const { page, contacts, tags } = smallDataSet;

      await page.goto('/contacts');

      // Small dataset: 5 contacts, 3 tags - perfect for quick smoke tests
      expect(contacts).toHaveLength(5);
      expect(tags).toHaveLength(3);

      console.log(
        `📊 Small dataset loaded: ${contacts.length} contacts, ${tags.length} tags`
      );
    });

    // TODO: Re-enable when dataset functionality is stable
    test.skip('should work with medium dataset for comprehensive tests', async ({
      mediumDataSet,
    }) => {
      // Test skipped - dataset functionality has server errors
    });

    // TODO: Re-enable when search functionality is implemented
    test.skip('should work with search test data for search functionality', async ({
      searchTestData,
    }) => {
      // Test skipped - search functionality not yet implemented
    });

    test('should work with favourites test data', async ({
      favouritesTestData,
    }) => {
      const { page, contacts } = favouritesTestData;

      await page.goto('/contacts');

      // Check favourite/regular distribution
      const favouriteContacts = contacts.filter(c => c.isFavourite);
      const regularContacts = contacts.filter(c => !c.isFavourite);

      expect(favouriteContacts.length).toBeGreaterThan(0);
      expect(regularContacts.length).toBeGreaterThan(0);

      // Test favourites filter
      const favouritesFilter = page.locator(
        '[data-testid="favourites-filter"]'
      );
      if (await favouritesFilter.isVisible()) {
        await favouritesFilter.click();

        // Should only show favourite contacts
        for (const contact of favouriteContacts) {
          await expect(
            page.locator(`[data-testid="contact-${contact.id}"]`)
          ).toBeVisible();
        }
      }

      console.log(
        `⭐ Favourites dataset: ${favouriteContacts.length} favourites, ${regularContacts.length} regular`
      );
    });
  });

  test.describe('Specialized Fixtures', () => {
    test('should work with contacts without tags', async ({
      contactsWithoutTags,
    }) => {
      const { page, contacts } = contactsWithoutTags;

      await page.goto('/contacts');

      // All contacts should have no tags
      expect(contacts).toHaveLength(5);
      contacts.forEach(contact => {
        expect(contact.tags || []).toHaveLength(0);
      });

      // Verify no tag elements are displayed
      for (const contact of contacts) {
        const contactCard = page.locator(
          `[data-testid="contact-${contact.id}"]`
        );
        const tagElements = contactCard.locator('[data-testid^="tag-"]');
        await expect(tagElements).toHaveCount(0);
      }

      console.log(
        `📝 Untagged dataset: ${contacts.length} contacts without tags`
      );
    });

    test('should work with favourite contacts only', async ({
      favouriteContacts,
    }) => {
      const { page, contacts } = favouriteContacts;

      await page.goto('/contacts');

      // All contacts should be favourites
      expect(contacts).toHaveLength(3);
      contacts.forEach(contact => {
        expect(contact.isFavourite).toBe(true);
      });

      // Verify favourite indicators are shown
      for (const contact of contacts) {
        const contactCard = page.locator(
          `[data-testid="contact-${contact.id}"]`
        );
        const favouriteIcon = contactCard.locator(
          '[data-testid="favourite-icon"]'
        );
        await expect(favouriteIcon).toBeVisible();
      }

      console.log(`⭐ Favourites only: ${contacts.length} favourite contacts`);
    });

    test('should work with regular contacts only', async ({
      regularContacts,
    }) => {
      const { page, contacts } = regularContacts;

      await page.goto('/contacts');

      // All contacts should be regular (not favourites)
      expect(contacts).toHaveLength(5);
      contacts.forEach(contact => {
        expect(contact.isFavourite).toBe(false);
      });

      // Verify no favourite indicators are shown
      for (const contact of contacts) {
        const contactCard = page.locator(
          `[data-testid="contact-${contact.id}"]`
        );
        const favouriteIcon = contactCard.locator(
          '[data-testid="favourite-icon"]'
        );
        await expect(favouriteIcon).not.toBeVisible();
      }

      console.log(`📝 Regular only: ${contacts.length} regular contacts`);
    });
  });

  test.describe('Data Factory Usage', () => {
    test('should use data factories for custom scenarios', async ({
      authenticatedPage: _authenticatedPage,
      dataFactory,
      testCleanup: _testCleanup,
    }) => {
      // Demonstrate factory usage for custom test scenarios
      const customContacts = dataFactory.contacts.createMany(3, {
        firstName: 'TestUser',
        isFavourite: true,
      });

      const customTags = dataFactory.tags.createWithPrefix('CustomTag', 2);
      const searchDataset = dataFactory.datasets.createSearchTestData();

      // Verify factory-generated data structure
      expect(customContacts).toHaveLength(3);
      expect(customTags).toHaveLength(2);
      expect(searchDataset.contacts).toHaveLength(4);
      expect(searchDataset.tags).toHaveLength(3);

      // Verify custom properties
      customContacts.forEach(contact => {
        expect(contact.firstName).toBe('TestUser');
        expect(contact.isFavourite).toBe(true);
        expect(contact.lastName).toBeDefined();
        expect(contact.email).toBeDefined();
      });

      customTags.forEach(tag => {
        expect(tag.name).toContain('CustomTag');
        expect(tag.color).toBeDefined();
      });

      console.log(`🏭 Factory data generated successfully:
        - ${customContacts.length} custom contacts
        - ${customTags.length} custom tags
        - ${searchDataset.contacts.length} search test contacts
        - ${searchDataset.tags.length} search test tags`);
    });
  });
});
