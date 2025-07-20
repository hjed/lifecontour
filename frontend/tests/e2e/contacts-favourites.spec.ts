import { test, expect } from '@playwright/test';
import { createTestHelpers } from './utils/test-helpers';

/**
 * Contacts Page - Favourites Functionality Tests
 *
 * These tests set up their own test data to ensure deterministic behavior.
 * Each test creates the exact data state it needs to test specific functionality.
 */
test.describe('Contacts Page - Favourites Functionality', () => {
  test('should redirect to login when not authenticated', async ({ page }) => {
    const { testData } = createTestHelpers(page);

    // Set up test state: no authentication
    await testData.clearAllTestData();

    // Navigate to contacts page
    await page.goto('/contacts');
    await expect(page).toHaveTitle(/Personal Management System/);

    // Should redirect to login
    await page.waitForLoadState('networkidle');
    const currentUrl = page.url();
    expect(currentUrl).toContain('/auth/login');

    // Should show login form
    await expect(page.getByRole('heading', { name: 'Welcome Back' })).toBeVisible();
  });

  test('should display contacts page with proper structure when authenticated', async ({ page }) => {
    const { testData, contacts } = createTestHelpers(page);

    // Set up test state: authenticated user with contacts
    await testData.setupAuthenticatedUser();
    await testData.createTestContacts([
      { firstName: 'John', lastName: 'Doe', email: 'john@example.com' },
      { firstName: 'Jane', lastName: 'Smith', email: 'jane@example.com' },
    ]);

    // Navigate to contacts page
    await page.goto('/contacts');
    await expect(page).toHaveTitle(/Personal Management System/);

    // Should display contacts with proper structure
    await contacts.testPageStructure();

    // Should show exactly 2 contacts
    const contactCards = await contacts.waitForContactCards();
    expect(await contactCards.count()).toBe(2);
  });

  test('should display favourite toggle buttons on contact cards', async ({
    page,
  }) => {
    const { testData, contacts } = createTestHelpers(page);

    // Set up test state: authenticated user with contacts
    await testData.setupAuthenticatedUser();
    await testData.createTestContacts([
      { firstName: 'John', lastName: 'Doe', email: 'john@example.com', isFavourite: false },
      { firstName: 'Jane', lastName: 'Smith', email: 'jane@example.com', isFavourite: true },
    ]);

    // Navigate to contacts page
    await page.goto('/contacts');
    await expect(page).toHaveTitle(/Personal Management System/);

    // Should show 2 contacts with favourite buttons
    const contactCards = await contacts.waitForContactCards();
    expect(await contactCards.count()).toBe(2);

    // Test favourite button functionality
    await contacts.testFavouriteButtons();
  });

  test('should allow clicking favourite toggle buttons', async ({ page }) => {
    const { testData, contacts } = createTestHelpers(page);

    // Set up test state: authenticated user with contacts
    await testData.setupAuthenticatedUser();
    await testData.createTestContacts([
      { firstName: 'John', lastName: 'Doe', email: 'john@example.com', isFavourite: false },
    ]);

    // Navigate to contacts page
    await page.goto('/contacts');
    await expect(page).toHaveTitle(/Personal Management System/);

    // Should show 1 contact
    const contactCards = await contacts.waitForContactCards();
    expect(await contactCards.count()).toBe(1);

    // Should be able to click favourite button
    await contacts.clickFavouriteButton();
  });

  test('should display contact cards with proper structure', async ({ page }) => {
    const { testData, contacts } = createTestHelpers(page);

    // Set up test state: authenticated user with contacts
    await testData.setupAuthenticatedUser();
    await testData.createTestContacts([
      { firstName: 'John', lastName: 'Doe', email: 'john@example.com' },
      { firstName: 'Jane', lastName: 'Smith', email: 'jane@example.com' },
    ]);

    // Navigate to contacts page
    await page.goto('/contacts');
    await expect(page).toHaveTitle(/Personal Management System/);

    // Should show 2 contacts with proper structure
    const contactCards = await contacts.waitForContactCards();
    expect(await contactCards.count()).toBe(2);

    await contacts.verifyContactCardStructure();
  });

  test('should display empty state when no contacts exist', async ({ page }) => {
    const { testData } = createTestHelpers(page);

    // Set up test state: authenticated user with no contacts
    await testData.setupAuthenticatedUser();

    // Navigate to contacts page
    await page.goto('/contacts');
    await expect(page).toHaveTitle(/Personal Management System/);

    // Should show empty state
    const emptyState = page.locator('text=/no contacts/i, text=/create.*contact/i');
    await expect(emptyState).toBeVisible();

    // Should not show any contact cards
    const contactCards = page.locator('[data-testid="contact-card"], .contact-card, [class*="card"]');
    expect(await contactCards.count()).toBe(0);
  });

  test('should maintain responsive design with favourite toggles', async ({
    page,
  }) => {
    const { testData, contacts } = createTestHelpers(page);

    // Set up test state: authenticated user with contacts
    await testData.setupAuthenticatedUser();
    await testData.createTestContacts([
      { firstName: 'John', lastName: 'Doe', email: 'john@example.com', isFavourite: true },
    ]);

    // Navigate to contacts page
    await page.goto('/contacts');
    await expect(page).toHaveTitle(/Personal Management System/);

    // Test responsive design
    await contacts.testResponsiveFavouriteToggles();
  });
});
