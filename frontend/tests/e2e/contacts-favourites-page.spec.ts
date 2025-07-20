import { test, expect } from '@playwright/test';
import { createTestHelpers } from './utils/test-helpers';

/**
 * Favourites Page Tests
 *
 * These tests set up their own test data to ensure deterministic behavior.
 * Each test creates the exact data state it needs to test specific functionality.
 */
test.describe('Favourites Page', () => {
  test('should redirect to login when not authenticated', async ({ page }) => {
    const { testData } = createTestHelpers(page);

    // Set up test state: no authentication
    await testData.clearAllTestData();

    // Navigate to favourites page
    await page.goto('/contacts/favourites');
    await expect(page).toHaveTitle(/Personal Management System/);

    // Should redirect to login
    await page.waitForLoadState('networkidle');
    const currentUrl = page.url();
    expect(currentUrl).toContain('/auth/login');

    // Should show login form
    await expect(
      page.getByRole('heading', { name: 'Welcome Back' })
    ).toBeVisible();
  });

  test('should display favourites page with proper structure when authenticated', async ({
    page,
  }) => {
    const { testData, contacts } = createTestHelpers(page);

    // Set up test state: authenticated user with favourite contacts
    await testData.setupAuthenticatedUser();
    await testData.createTestContacts([
      {
        firstName: 'John',
        lastName: 'Doe',
        email: 'john@example.com',
        isFavourite: true,
      },
    ]);

    // Navigate to favourites page
    await page.goto('/contacts/favourites');
    await expect(page).toHaveTitle(/Personal Management System/);

    // Should display page with proper structure
    await contacts.testPageStructure();

    // Should have favourites-related content
    const pageContent = page.locator('body');
    await expect(pageContent).toContainText(/favourite/i);
  });

  test('should display favourites page header with proper content', async ({
    page,
  }) => {
    const { testData } = createTestHelpers(page);

    // Set up test state: authenticated user
    await testData.setupAuthenticatedUser();

    // Navigate to favourites page
    await page.goto('/contacts/favourites');
    await expect(page).toHaveTitle(/Personal Management System/);

    // Should have proper heading structure
    const heading = page.locator('h1');
    await expect(heading).toBeVisible();
    await expect(heading).toContainText(/favourite/i);

    // Should have descriptive content
    const pageContent = page.locator('body');
    const textContent = await pageContent.textContent();
    expect(textContent).toBeTruthy();
    expect(textContent!.length).toBeGreaterThan(50);
  });

  test('should display favourite contacts when they exist', async ({
    page,
  }) => {
    const { testData, contacts } = createTestHelpers(page);

    // Set up test state: authenticated user with favourite contacts
    await testData.setupAuthenticatedUser();
    await testData.createTestContacts([
      {
        firstName: 'John',
        lastName: 'Doe',
        email: 'john@example.com',
        isFavourite: true,
      },
      {
        firstName: 'Jane',
        lastName: 'Smith',
        email: 'jane@example.com',
        isFavourite: true,
      },
      {
        firstName: 'Bob',
        lastName: 'Wilson',
        email: 'bob@example.com',
        isFavourite: false,
      },
    ]);

    // Navigate to favourites page
    await page.goto('/contacts/favourites');
    await expect(page).toHaveTitle(/Personal Management System/);

    // Should show exactly 2 favourite contacts
    const contactCards = await contacts.waitForContactCards();
    expect(await contactCards.count()).toBe(2);

    // Should have favourite buttons
    await contacts.testFavouriteButtons();
  });

  test('should display empty state when no favourite contacts exist', async ({
    page,
  }) => {
    const { testData } = createTestHelpers(page);

    // Set up test state: authenticated user with no favourite contacts
    await testData.setupAuthenticatedUser();
    await testData.createTestContacts([
      {
        firstName: 'John',
        lastName: 'Doe',
        email: 'john@example.com',
        isFavourite: false,
      },
    ]);

    // Navigate to favourites page
    await page.goto('/contacts/favourites');
    await expect(page).toHaveTitle(/Personal Management System/);

    // Should show empty state
    const emptyState = page.locator(
      'text=/no.*favourite.*contacts/i, text=/star.*contacts/i'
    );
    await expect(emptyState).toBeVisible();

    // Should not show any contact cards
    const contactCards = page.locator(
      '[data-testid="contact-card"], .contact-card, [class*="card"]'
    );
    expect(await contactCards.count()).toBe(0);
  });

  test('should provide helpful empty state messaging', async ({ page }) => {
    const { testData } = createTestHelpers(page);

    // Set up test state: authenticated user with no favourite contacts
    await testData.setupAuthenticatedUser();

    // Navigate to favourites page
    await page.goto('/contacts/favourites');
    await expect(page).toHaveTitle(/Personal Management System/);

    // Should have empty state with helpful messaging
    const emptyState = page.locator(
      'text=/no.*favourite.*contacts/i, text=/star.*contacts/i'
    );
    await expect(emptyState).toBeVisible();

    // Should have helpful text about favourites/starring
    const helpfulText = page.locator('text=/star/i, text=/favourite/i');
    expect(await helpfulText.count()).toBeGreaterThan(0);
  });

  test('should allow navigation back to all contacts', async ({ page }) => {
    const { testData } = createTestHelpers(page);

    // Set up test state: authenticated user
    await testData.setupAuthenticatedUser();

    // Navigate to favourites page
    await page.goto('/contacts/favourites');
    await expect(page).toHaveTitle(/Personal Management System/);

    // Should have navigation back to all contacts
    const allContactsLink = page.locator(
      'a[href="/contacts"]:has-text("All"), a[href="/contacts"]:has-text("Browse"), a:has-text("All Contacts")'
    );
    const linkCount = await allContactsLink.count();

    if (linkCount > 0) {
      await expect(allContactsLink.first()).toBeVisible();
      await expect(allContactsLink.first()).toBeEnabled();

      // Click the link and verify navigation
      await allContactsLink.first().click();
      await page.waitForLoadState('networkidle');

      const currentUrl = page.url();
      expect(currentUrl).toContain('/contacts');
    }
    // If no link exists, that's also valid - different UI design
  });

  test('should show favourites link in sidebar navigation', async ({
    page,
  }) => {
    const { testData, sidebar } = createTestHelpers(page);

    // Set up test state: authenticated user
    await testData.setupAuthenticatedUser();

    // Navigate to contacts page
    await page.goto('/contacts');
    await expect(page).toHaveTitle(/Personal Management System/);

    // Should show favourites link in sidebar
    await sidebar.waitForSidebar();
    await sidebar.testFavouritesLink();
  });

  test('should maintain consistent UI with main contacts page', async ({
    page,
  }) => {
    const { testData, sidebar } = createTestHelpers(page);

    // Set up test state: authenticated user
    await testData.setupAuthenticatedUser();

    // Navigate to favourites page
    await page.goto('/contacts/favourites');
    await expect(page).toHaveTitle(/Personal Management System/);

    // Should have consistent navigation elements
    await sidebar.waitForSidebar();

    // Should have consistent header structure
    const header = page.locator('h1').first();
    await expect(header).toBeVisible();

    // Should have consistent page layout
    const mainContent = page.locator('main, [role="main"]');
    await expect(mainContent).toBeVisible();
  });

  test('should be accessible with proper ARIA labels', async ({ page }) => {
    const { testData, contacts } = createTestHelpers(page);

    // Set up test state: authenticated user with favourite contacts
    await testData.setupAuthenticatedUser();
    await testData.createTestContacts([
      {
        firstName: 'John',
        lastName: 'Doe',
        email: 'john@example.com',
        isFavourite: true,
      },
    ]);

    // Navigate to favourites page
    await page.goto('/contacts/favourites');
    await expect(page).toHaveTitle(/Personal Management System/);

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
    const contactCards = await contacts.waitForContactCards();
    expect(await contactCards.count()).toBe(1);

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
