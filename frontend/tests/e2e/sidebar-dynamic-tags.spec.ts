import { test, expect } from './fixtures';
import { createTestHelpers } from './utils/test-helpers';

/**
 * Sidebar Dynamic Tags Navigation Tests
 *
 * These tests set up their own test data to ensure deterministic behavior.
 * Each test creates the exact data state it needs to test specific functionality.
 *
 * Converted to use the advanced fixture-based testing system.
 */
test.describe('Sidebar Dynamic Tags Navigation', () => {
  test('should display sidebar with proper structure', async ({
    authenticatedPage: page,
  }) => {
    const { sidebar } = createTestHelpers(page);

    // Navigate to contacts page
    await page.goto('/contacts');
    await expect(page).toHaveTitle(/Personal Management System/);

    // Sidebar should be visible and properly structured
    await sidebar.testSidebarStructure();
  });

  test('should never display hardcoded groups in sidebar', async ({
    authenticatedPage: page,
  }) => {
    const { sidebar } = createTestHelpers(page);

    // Navigate to contacts page
    await page.goto('/contacts');
    await expect(page).toHaveTitle(/Personal Management System/);

    // Should never have hardcoded groups
    await sidebar.testNoHardcodedGroups();
  });

  test('should display dynamic tag links when tags exist', async ({
    authenticatedPage: page,
  }) => {
    const { testData, sidebar } = createTestHelpers(page);

    // Set up test state: authenticated user with tags
    await testData.createTestTags(['work', 'family', 'friends']);
    await testData.createTestContacts([
      { firstName: 'John', lastName: 'Doe', tags: ['work'] },
      { firstName: 'Jane', lastName: 'Smith', tags: ['family'] },
    ]);

    // Navigate to contacts page
    await page.goto('/contacts');
    await expect(page).toHaveTitle(/Personal Management System/);

    // Wait for sidebar to be fully loaded
    await sidebar.waitForSidebar();

    // Wait for tags to be loaded by checking if tag links are present
    // This ensures React Query has finished loading the tags
    const tagLinks = page.locator('a[href*="/contacts/tags/"]');
    await expect(tagLinks.first()).toBeVisible();

    const tagCount = await tagLinks.count();
    expect(tagCount).toBeGreaterThan(0);

    // First tag link should be properly structured
    const firstTag = tagLinks.first();
    await expect(firstTag).toBeVisible();
    await expect(firstTag).toHaveAttribute('href');

    const href = await firstTag.getAttribute('href');
    expect(href).toMatch(/\/contacts\/tags\/\w+/);
  });

  test('should display favourites link in sidebar', async ({
    authenticatedPage: page,
  }) => {
    const { sidebar } = createTestHelpers(page);

    // Navigate to contacts page
    await page.goto('/contacts');
    await expect(page).toHaveTitle(/Personal Management System/);

    // Should show favourites link
    await sidebar.testFavouritesLink();
  });

  test('should display all contacts link in sidebar', async ({
    authenticatedPage: page,
  }) => {
    const { sidebar } = createTestHelpers(page);

    // Navigate to contacts page
    await page.goto('/contacts');
    await expect(page).toHaveTitle(/Personal Management System/);

    await sidebar.waitForSidebar();

    // Should have "All" contacts link
    const allContactsLink = page.locator('a[href="/contacts"]:has-text("All")');
    await expect(allContactsLink).toBeVisible();
    await expect(allContactsLink).toBeEnabled();

    const linkText = await allContactsLink.textContent();
    expect(linkText?.toLowerCase()).toContain('all');
  });

  test('should allow navigation to tag pages from sidebar', async ({
    authenticatedPage: page,
  }) => {
    const { testData, sidebar } = createTestHelpers(page);

    // Set up test state: authenticated user with tags
    await testData.createTestTags(['work']);
    await testData.createTestContacts([
      { firstName: 'John', lastName: 'Doe', tags: ['work'] },
    ]);

    // Navigate to contacts page
    await page.goto('/contacts');
    await expect(page).toHaveTitle(/Personal Management System/);

    await sidebar.waitForSidebar();

    // Click on work tag link
    const workTagLink = page.locator(
      'a[href*="/contacts/tags/"]:has-text("work")'
    );
    await expect(workTagLink).toBeVisible();
    await workTagLink.click();
    await page.waitForLoadState('networkidle');

    // Should navigate to work tag page
    expect(page.url()).toContain('/contacts/tags/');

    // Should show work tag content
    const pageContent = page.locator('body');
    await expect(pageContent).toContainText(/work/i);
  });

  test('should allow navigation to favourites page from sidebar', async ({
    authenticatedPage: page,
  }) => {
    const { sidebar } = createTestHelpers(page);

    // Navigate to contacts page
    await page.goto('/contacts');
    await expect(page).toHaveTitle(/Personal Management System/);

    // Navigate to favourites via sidebar
    await sidebar.navigateToFavourites();

    // Should be on favourites page
    expect(page.url()).toContain('/contacts/favourites');
  });

  test('should display basic navigation items in sidebar', async ({
    authenticatedPage: page,
  }) => {
    const { sidebar } = createTestHelpers(page);

    // Navigate to contacts page
    await page.goto('/contacts');
    await expect(page).toHaveTitle(/Personal Management System/);

    await sidebar.waitForSidebar();

    // Should have basic navigation items
    const allContactsLink = page.locator('a[href="/contacts"]');
    const favouritesLink = page.locator('a[href="/contacts/favourites"]');

    // At least one of these should be visible
    const allVisible = await allContactsLink.isVisible();
    const favVisible = await favouritesLink.isVisible();
    expect(allVisible || favVisible).toBe(true);
  });

  test('should display contacts section in sidebar', async ({
    authenticatedPage: page,
  }) => {
    const { sidebar } = createTestHelpers(page);

    // Navigate to contacts page
    await page.goto('/contacts');
    await expect(page).toHaveTitle(/Personal Management System/);

    await sidebar.waitForSidebar();

    // Should have contact-related navigation items
    const contactNavItems = page.locator('a[href*="/contacts"]');
    const navItemCount = await contactNavItems.count();
    expect(navItemCount).toBeGreaterThanOrEqual(1);
  });

  test('should highlight active page in sidebar navigation', async ({
    authenticatedPage: page,
  }) => {
    const { sidebar } = createTestHelpers(page);

    // Navigate to favourites page
    await page.goto('/contacts/favourites');
    await expect(page).toHaveTitle(/Personal Management System/);

    await sidebar.waitForSidebar();

    // Favourites link should have active state indicators
    const favouritesLink = page.locator('a[href="/contacts/favourites"]');
    await expect(favouritesLink).toBeVisible();

    const linkElement = favouritesLink.first();
    const ariaCurrent = await linkElement.getAttribute('aria-current');
    const className = await linkElement.getAttribute('class');

    // Should have some indication of active state
    expect(
      ariaCurrent === 'page' || (className && className.includes('active'))
    ).toBe(true);
  });

  test('should be responsive on mobile devices', async ({
    authenticatedPage: page,
  }) => {
    const { sidebar } = createTestHelpers(page);

    // Navigate to contacts page
    await page.goto('/contacts');
    await expect(page).toHaveTitle(/Personal Management System/);

    // Test mobile responsiveness
    await sidebar.testMobileSidebar();
  });
});
