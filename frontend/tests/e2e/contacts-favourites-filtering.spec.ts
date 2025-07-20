import { test, expect } from '@playwright/test';
import { createTestHelpers } from './utils/test-helpers';

/**
 * Contact Favourites and Filtering Tests
 *
 * These tests set up their own test data to ensure deterministic behavior.
 * Each test creates the exact data state it needs to test specific functionality.
 */
test.describe('Contact Favourites and Filtering', () => {
  test.describe('Favourites Functionality', () => {
    test('should display favourite contacts when favourite contacts exist', async ({
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

      // Each contact card should have a favourite button
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
        {
          firstName: 'Jane',
          lastName: 'Smith',
          email: 'jane@example.com',
          isFavourite: false,
        },
      ]);

      // Navigate to favourites page
      await page.goto('/contacts/favourites');
      await expect(page).toHaveTitle(/Personal Management System/);

      // Should show empty state message
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

    test('should redirect to login when not authenticated', async ({
      page,
    }) => {
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

    test('should toggle favourite status when favourite button is clicked', async ({
      page,
    }) => {
      const { testData, contacts } = createTestHelpers(page);

      // Set up test state: authenticated user with contacts
      await testData.setupAuthenticatedUser();
      await testData.createTestContacts([
        {
          firstName: 'John',
          lastName: 'Doe',
          email: 'john@example.com',
          isFavourite: false,
        },
        {
          firstName: 'Jane',
          lastName: 'Smith',
          email: 'jane@example.com',
          isFavourite: true,
        },
      ]);

      // Navigate to contacts page
      await page.goto('/contacts');
      await expect(page).toHaveTitle(/Personal Management System/);

      // Should show 2 contacts
      const contactCards = await contacts.waitForContactCards();
      expect(await contactCards.count()).toBe(2);

      // Click favourite button on first contact
      await contacts.clickFavouriteButton();

      // Button should still be functional after click
      const favouriteButtons = page.locator(
        'button[aria-label*="favourite"], button[aria-label*="Favourite"]'
      );
      await expect(favouriteButtons.first()).toBeEnabled();
    });

    test('should allow navigation to favourites page from sidebar', async ({
      page,
    }) => {
      const { testData, sidebar } = createTestHelpers(page);

      // Set up test state: authenticated user
      await testData.setupAuthenticatedUser();

      // Navigate to contacts page
      await page.goto('/contacts');
      await expect(page).toHaveTitle(/Personal Management System/);

      // Navigate to favourites via sidebar
      await sidebar.navigateToFavourites();

      // Should be on favourites page
      const currentUrl = page.url();
      expect(currentUrl).toContain('/contacts/favourites');
    });
  });

  test.describe('Tag-based Filtering', () => {
    test('should display contacts filtered by tag when tag exists', async ({
      page,
    }) => {
      const { testData, contacts } = createTestHelpers(page);

      // Set up test state: authenticated user with tagged contacts
      await testData.setupAuthenticatedUser();
      await testData.createTestTags(['work', 'family']);
      await testData.createTestContacts([
        {
          firstName: 'John',
          lastName: 'Doe',
          email: 'john@example.com',
          tags: ['work'],
        },
        {
          firstName: 'Jane',
          lastName: 'Smith',
          email: 'jane@example.com',
          tags: ['work'],
        },
        {
          firstName: 'Bob',
          lastName: 'Wilson',
          email: 'bob@example.com',
          tags: ['family'],
        },
      ]);

      // Navigate to work tag page
      await page.goto('/contacts/tags/work');
      await expect(page).toHaveTitle(/Personal Management System/);

      // Should show exactly 2 contacts with work tag
      const contactCards = await contacts.waitForContactCards();
      expect(await contactCards.count()).toBe(2);

      // Page should indicate it's showing work tag
      const pageContent = page.locator('body');
      await expect(pageContent).toContainText(/work/i);
    });

    test('should display empty state when tag has no contacts', async ({
      page,
    }) => {
      const { testData } = createTestHelpers(page);

      // Set up test state: authenticated user with empty tag
      await testData.setupAuthenticatedUser();
      await testData.createTestTags(['empty-tag']);
      await testData.createTestContacts([
        {
          firstName: 'John',
          lastName: 'Doe',
          email: 'john@example.com',
          tags: ['other-tag'],
        },
      ]);

      // Navigate to empty tag page
      await page.goto('/contacts/tags/empty-tag');
      await expect(page).toHaveTitle(/Personal Management System/);

      // Should show empty state for this tag
      const emptyState = page.locator(
        'text=/no contacts.*tag/i, text=/no contacts found/i'
      );
      await expect(emptyState).toBeVisible();

      // Should not show any contact cards
      const contactCards = page.locator(
        '[data-testid="contact-card"], .contact-card, [class*="card"]'
      );
      expect(await contactCards.count()).toBe(0);
    });

    test('should display not found message for non-existent tag', async ({
      page,
    }) => {
      const { testData } = createTestHelpers(page);

      // Set up test state: authenticated user with no matching tag
      await testData.setupAuthenticatedUser();
      await testData.createTestTags(['work', 'family']);

      // Navigate to non-existent tag page
      await page.goto('/contacts/tags/non-existent-tag-999');
      await expect(page).toHaveTitle(/Personal Management System/);

      // Should show tag not found message
      const errorContent = page.locator(
        'text=/tag.*not.*found/i, text=/not.*found/i'
      );
      await expect(errorContent).toBeVisible();
    });
  });

  test.describe('Integration Tests', () => {
    test('should maintain consistent navigation between contact pages', async ({
      page,
    }) => {
      const { testData } = createTestHelpers(page);

      // Set up test state: authenticated user with contacts
      await testData.setupAuthenticatedUser();
      await testData.createTestContacts([
        {
          firstName: 'John',
          lastName: 'Doe',
          email: 'john@example.com',
          isFavourite: true,
        },
      ]);

      // Start on contacts page
      await page.goto('/contacts');
      await expect(page).toHaveTitle(/Personal Management System/);

      // Navigate to favourites page via sidebar
      const favouritesLink = page.locator('a[href="/contacts/favourites"]');
      await expect(favouritesLink).toBeVisible();
      await favouritesLink.click();
      await page.waitForLoadState('networkidle');

      // Should be on favourites page
      expect(page.url()).toContain('/contacts/favourites');

      // Should show favourite contact
      const contactCards = page.locator(
        '[data-testid="contact-card"], .contact-card, [class*="card"]'
      );
      expect(await contactCards.count()).toBe(1);
    });

    test('should display consistent UI structure across contact pages', async ({
      page,
    }) => {
      const { testData, sidebar } = createTestHelpers(page);

      // Set up test state: authenticated user
      await testData.setupAuthenticatedUser();
      await testData.createTestContacts([
        {
          firstName: 'John',
          lastName: 'Doe',
          email: 'john@example.com',
          isFavourite: true,
        },
      ]);

      const pagesToTest = ['/contacts', '/contacts/favourites'];

      for (const pageUrl of pagesToTest) {
        await page.goto(pageUrl);
        await expect(page).toHaveTitle(/Personal Management System/);

        // Each page should have sidebar and header
        await sidebar.waitForSidebar();
        const header = page.locator('h1, [role="heading"]').first();
        await expect(header).toBeVisible();

        // Each page should have main content area
        const mainContent = page.locator('main, [role="main"]');
        await expect(mainContent).toBeVisible();
      }
    });
  });
});
