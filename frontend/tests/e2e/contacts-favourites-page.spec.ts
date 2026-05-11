import { test, expect } from './fixtures';

/**
 * Favourites Page Tests
 *
 * Converted to use the advanced fixture-based testing system.
 * Each test uses deterministic fixtures that provide guaranteed data state.
 */
test.describe('Favourites Page', () => {
  test('should redirect to login when not authenticated', async ({
    unauthenticatedPage,
  }) => {
    // Navigate to favourites page
    await unauthenticatedPage.goto('/contacts/favourites');
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

  test('should display favourites page with proper structure when authenticated', async ({
    favouriteContacts,
  }) => {
    const { page, contacts } = favouriteContacts;

    // Navigate to favourites page
    await page.goto('/contacts/favourites');
    await expect(page).toHaveTitle(/Personal Management System/);

    // Verify we have favourite contacts (guaranteed by fixture)
    expect(contacts.length).toBeGreaterThan(0);
    contacts.forEach(contact => {
      expect(contact.isFavourite).toBe(true);
    });

    // Should have favourites-related content
    const pageContent = page.locator('body');
    await expect(pageContent).toContainText(/favourite/i);

    // Verify favourite contacts are displayed
    for (const contact of contacts) {
      const contactCard = page.locator(`[data-testid="contact-${contact.id}"]`);
      await expect(contactCard).toBeVisible();
    }
  });

  test('should display favourites page header with proper content', async ({
    authenticatedPage,
  }) => {
    // Navigate to favourites page
    await authenticatedPage.goto('/contacts/favourites');
    await expect(authenticatedPage).toHaveTitle(/Personal Management System/);

    // Should have proper heading structure
    const heading = authenticatedPage.locator('h1');
    await expect(heading).toBeVisible();
    await expect(heading).toContainText(/favourite/i);

    // Should have descriptive content
    const pageContent = authenticatedPage.locator('body');
    const textContent = await pageContent.textContent();
    expect(textContent).toBeTruthy();
    expect(textContent!.length).toBeGreaterThan(50);
  });

  test('should display favourite contacts when they exist', async ({
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
      const contactCard = page.locator(`[data-testid="contact-${contact.id}"]`);
      await expect(contactCard).toBeVisible();

      // Should have favourite button
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

    // Should show empty state
    const emptyState = page.locator('[data-testid="empty-state"]');
    await expect(emptyState).toBeVisible();

    // Verify the empty state contains the expected text
    await expect(emptyState).toContainText('No favourite contacts found');

    // Should not show any contact cards (exclude empty state card)
    const contactCards = page.locator('[data-testid^="contact-"]');
    expect(await contactCards.count()).toBe(0);
  });

  test('should provide helpful empty state messaging', async ({
    emptyContactsPage,
  }) => {
    // Navigate to favourites page
    await emptyContactsPage.goto('/contacts/favourites');
    await expect(emptyContactsPage).toHaveTitle(/Personal Management System/);

    // Should have empty state with helpful messaging
    const emptyState = emptyContactsPage.locator('[data-testid="empty-state"]');
    await expect(emptyState).toBeVisible();

    // Check for the specific text that the frontend actually displays
    await expect(emptyState).toContainText('No favourite contacts found');

    // Should have helpful text about favourites/starring
    await expect(emptyState).toContainText(
      'Star some contacts to see them here'
    );
  });

  test('should allow navigation back to all contacts', async ({
    emptyContactsPage,
  }) => {
    // Navigate to favourites page
    await emptyContactsPage.goto('/contacts/favourites');
    await expect(emptyContactsPage).toHaveTitle(/Personal Management System/);

    // Should have navigation back to all contacts in the empty state
    const emptyStateLink = emptyContactsPage.locator(
      '[data-testid="empty-state"] a[href="/contacts"]'
    );

    await expect(emptyStateLink).toBeVisible();
    await expect(emptyStateLink).toBeEnabled();

    // Click the link and verify navigation
    await Promise.all([
      emptyContactsPage.waitForURL('**/contacts'),
      emptyStateLink.click(),
    ]);

    const currentUrl = emptyContactsPage.url();
    expect(currentUrl).toContain('/contacts');
    // If no link exists, that's also valid - different UI design
  });

  test('should show favourites link in sidebar navigation', async ({
    authenticatedPage,
  }) => {
    // Navigate to contacts page
    await authenticatedPage.goto('/contacts');
    await expect(authenticatedPage).toHaveTitle(/Personal Management System/);

    // We just need to use SidebarTestHelpers which handles mobile drawer properly
    const { SidebarTestHelpers } = await import('./utils/test-helpers');
    const sidebarHelpers = new SidebarTestHelpers(authenticatedPage);

    // Test favourites link specifically
    await sidebarHelpers.testFavouritesLink();
  });

  test('should maintain consistent UI with main contacts page', async ({
    authenticatedPage,
  }) => {
    // Navigate to favourites page
    await authenticatedPage.goto('/contacts/favourites');
    await expect(authenticatedPage).toHaveTitle(/Personal Management System/);

    // Should have consistent navigation elements
    const { SidebarTestHelpers } = await import('./utils/test-helpers');
    const sidebarHelpers = new SidebarTestHelpers(authenticatedPage);
    await sidebarHelpers.waitForSidebar();

    // Should have consistent header structure
    const header = authenticatedPage.locator('h1').first();
    await expect(header).toBeVisible();

    // Should have consistent page layout
    const mainContent = authenticatedPage.locator('main, [role="main"]');
    await expect(mainContent).toBeVisible();
  });

  test('should be accessible with proper ARIA labels', async ({
    favouriteContacts,
  }) => {
    const { page, contacts } = favouriteContacts;

    // Navigate to favourites page
    await page.goto('/contacts/favourites');
    await expect(page).toHaveTitle(/Personal Management System/);

    // Verify we have favourite contacts (guaranteed by fixture)
    expect(contacts.length).toBeGreaterThan(0);
    contacts.forEach(contact => {
      expect(contact.isFavourite).toBe(true);
    });

    // Check for proper heading structure
    const mainHeading = page.locator('h1');
    await expect(mainHeading).toBeVisible();

    // Check for proper navigation labels
    const navigation = page.locator('[role="navigation"]');
    const navCount = await navigation.count();
    if (navCount > 0) {
      const firstNav = navigation.first();
      const ariaLabel = await firstNav.getAttribute('aria-label');
      expect(ariaLabel).toBeTruthy();
    }

    // Check favourite buttons have proper labels
    // Verify we have favourite contacts (guaranteed by fixture)
    expect(contacts.length).toBeGreaterThan(0);

    // Check contact cards are displayed
    for (const contact of contacts) {
      const contactCard = page.locator(`[data-testid="contact-${contact.id}"]`);
      await expect(contactCard).toBeVisible();
    }

    const favouriteButtons = page.locator(
      'button[aria-label*="favourite"], button[aria-label*="Favourite"]'
    );
    const buttonCount = await favouriteButtons.count();
    expect(buttonCount).toBeGreaterThan(0);

    const firstButton = favouriteButtons.first();
    const ariaLabel = await firstButton.getAttribute('aria-label');
    expect(ariaLabel).toBeTruthy();
    expect(ariaLabel?.toLowerCase()).toContain('favourite');
  });
});
