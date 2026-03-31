import { test, expect } from './fixtures';

/**
 * Contacts Page - Favourites Functionality Tests
 *
 * Converted to use the advanced fixture-based testing system.
 * Each test uses deterministic fixtures that provide guaranteed data state.
 */
test.describe('Contacts Page - Favourites Functionality', () => {
  test('should redirect to login when not authenticated', async ({
    unauthenticatedPage,
  }) => {
    // Navigate to contacts page
    await unauthenticatedPage.goto('/contacts');
    await expect(unauthenticatedPage).toHaveTitle(/Personal Management System/);

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

  test('should display contacts page with proper structure when authenticated', async ({
    contactsWithData,
  }) => {
    const { page, contacts } = contactsWithData;

    // Navigate to contacts page
    await page.goto('/contacts');
    await expect(page).toHaveTitle(/Personal Management System/);

    // Should show exactly 2 contacts (guaranteed by fixture)
    expect(contacts).toHaveLength(2);

    // Verify contacts are displayed
    for (const contact of contacts) {
      await expect(
        page.locator(`[data-testid="contact-${contact.id}"]`)
      ).toBeVisible();
    }
  });

  test('should display favourite toggle buttons on contact cards', async ({
    favouritesTestData,
  }) => {
    const { page, contacts } = favouritesTestData;

    // Navigate to contacts page
    await page.goto('/contacts');
    await expect(page).toHaveTitle(/Personal Management System/);

    // Should show contacts with mixed favourite states (guaranteed by fixture)
    const favouriteContacts = contacts.filter(c => c.isFavourite);
    const regularContacts = contacts.filter(c => !c.isFavourite);

    expect(favouriteContacts.length).toBeGreaterThan(0);
    expect(regularContacts.length).toBeGreaterThan(0);

    // Verify favourite buttons are present for all contacts
    for (const contact of contacts) {
      const contactCard = page.locator(`[data-testid="contact-${contact.id}"]`);
      const favouriteButton = contactCard.locator(
        '[data-testid="favourite-toggle"]'
      );
      await expect(favouriteButton).toBeVisible();
    }
  });

  test('should allow clicking favourite toggle buttons', async ({
    regularContacts,
  }) => {
    const { page, contacts } = regularContacts;

    // Navigate to contacts page
    await page.goto('/contacts');
    await expect(page).toHaveTitle(/Personal Management System/);

    // Should show contacts (all non-favourite by fixture)
    expect(contacts.length).toBeGreaterThan(0);
    contacts.forEach(contact => {
      expect(contact.isFavourite).toBe(false);
    });

    // Should be able to click favourite button on first contact
    const firstContact = contacts[0];
    const contactCard = page.locator(
      `[data-testid="contact-${firstContact.id}"]`
    );
    const favouriteButton = contactCard.locator(
      '[data-testid="favourite-toggle"]'
    );

    await expect(favouriteButton).toBeVisible();
    await favouriteButton.click();

    // Button should be clickable (actual functionality testing would require API integration)
  });

  test('should display contact cards with proper structure', async ({
    contactsWithData,
  }) => {
    const { page, contacts } = contactsWithData;

    // Navigate to contacts page
    await page.goto('/contacts');
    await expect(page).toHaveTitle(/Personal Management System/);

    // Should show contacts with proper structure (guaranteed by fixture)
    expect(contacts).toHaveLength(2);

    // Verify each contact card has proper structure
    for (const contact of contacts) {
      const contactCard = page.locator(`[data-testid="contact-${contact.id}"]`);
      await expect(contactCard).toBeVisible();

      // Verify contact name is displayed
      await expect(contactCard).toContainText(
        `${contact.firstName} ${contact.lastName}`
      );
    }
  });

  test('should display empty state when no contacts exist', async ({
    emptyContactsPage,
  }) => {
    // Navigate to contacts page
    await emptyContactsPage.goto('/contacts');
    await expect(emptyContactsPage).toHaveTitle(/Personal Management System/);

    // Wait for authentication to complete and page to load
    await expect(
      emptyContactsPage.locator('main, [role="main"]').first()
    ).toBeVisible();

    // Wait for the empty state to appear (this ensures loading is complete)
    await expect(emptyContactsPage.getByText('0 contacts found')).toBeVisible();

    // Should show "No contacts found" heading
    await expect(
      emptyContactsPage.getByRole('heading', { name: /no contacts found/i })
    ).toBeVisible();

    // Should show "Add Contact" button
    await expect(
      emptyContactsPage.getByTestId('add-contact-button')
    ).toBeVisible();

    // Should not show any contact cards
    const contactCards = emptyContactsPage.locator('[data-testid^="contact-"]');
    expect(await contactCards.count()).toBe(0);
  });

  test('should maintain responsive design with favourite toggles', async ({
    favouriteContacts,
  }) => {
    const { page, contacts } = favouriteContacts;

    // Navigate to contacts page
    await page.goto('/contacts');
    await expect(page).toHaveTitle(/Personal Management System/);

    // Should show favourite contacts (guaranteed by fixture)
    expect(contacts.length).toBeGreaterThan(0);
    contacts.forEach(contact => {
      expect(contact.isFavourite).toBe(true);
    });

    // Test responsive design by checking different viewport sizes
    const viewports = [
      { width: 1200, height: 800 }, // Desktop
      { width: 768, height: 1024 }, // Tablet
      { width: 375, height: 667 }, // Mobile
    ];

    for (const viewport of viewports) {
      await page.setViewportSize(viewport);

      // Verify favourite toggles are still visible and accessible
      for (const contact of contacts) {
        const contactCard = page.locator(
          `[data-testid="contact-${contact.id}"]`
        );
        const favouriteButton = contactCard.locator(
          '[data-testid="favourite-toggle"]'
        );
        await expect(favouriteButton).toBeVisible();
      }
    }
  });
});
