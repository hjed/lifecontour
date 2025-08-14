import { test, expect } from './fixtures';

/**
 * Sidebar Navigation Tests
 *
 * Converted to use the advanced fixture-based testing system.
 * Each test uses deterministic fixtures that provide guaranteed authentication state.
 */
test.describe('Sidebar Navigation', () => {
  test.describe('Desktop Sidebar', () => {
    test('displays sidebar navigation on desktop', async ({
      authenticatedPage: page,
    }) => {
      // Set viewport to desktop size
      await page.setViewportSize({ width: 1024, height: 768 });

      // Navigate to contacts page
      await page.goto('/contacts');
      await expect(page).toHaveTitle(/Personal Management System/);

      // Check that desktop sidebar is visible
      const sidebar = page.getByTestId('sidebar');
      await expect(sidebar).toBeVisible();

      // Check navigation sections are present
      await expect(
        page.getByRole('button', { name: /contacts/i })
      ).toBeVisible();
      await expect(
        page.getByRole('button', { name: /journals/i })
      ).toBeVisible();
    });

    test('shows contacts section with proper navigation links', async ({
      taggedContactsData,
    }) => {
      const { page } = taggedContactsData;

      // Set viewport to desktop size
      await page.setViewportSize({ width: 1024, height: 768 });

      // Navigate to contacts page
      await page.goto('/contacts');
      await expect(page).toHaveTitle(/Personal Management System/);

      // Wait for sidebar to be fully loaded
      await page.waitForSelector('[role="navigation"]', { timeout: 10000 });

      // Should have basic navigation items
      await expect(page.getByTestId('nav-link-all')).toBeVisible({ timeout: 10000 });
      await expect(
        page.getByRole('link', { name: 'Favourites' })
      ).toBeVisible({ timeout: 10000 });

      // Should NOT have hardcoded groups
      await expect(
        page.getByRole('link', { name: 'Group 1' })
      ).not.toBeVisible();
      await expect(
        page.getByRole('link', { name: 'Group 2' })
      ).not.toBeVisible();

      // Should have dynamic tag links (wait for React Query to load tags)
      const tagLinks = page.locator('a[href*="/contacts/tags/"]');
      await expect(tagLinks.first()).toBeVisible({ timeout: 15000 }); // Wait up to 15 seconds for tags to load
      expect(await tagLinks.count()).toBeGreaterThan(0);
    });

    test('shows journals section collapsed by default', async ({
      authenticatedPage: page,
    }) => {
      // Set viewport to desktop size
      await page.setViewportSize({ width: 1024, height: 768 });

      // Navigate to contacts page
      await page.goto('/contacts');
      await expect(page).toHaveTitle(/Personal Management System/);

      // Journals section should be collapsed
      const journalsButton = page.getByRole('button', { name: /journals/i });
      await expect(journalsButton).toHaveAttribute('aria-expanded', 'false');

      // Journal navigation items should not be visible
      await expect(page.getByRole('link', { name: 'Etc' })).not.toBeVisible();
    });

    test('can toggle section expansion', async ({
      authenticatedPage: page,
    }) => {
      // Set viewport to desktop size
      await page.setViewportSize({ width: 1024, height: 768 });

      // Navigate to contacts page
      await page.goto('/contacts');
      await expect(page).toHaveTitle(/Personal Management System/);

      const journalsButton = page.getByRole('button', { name: /journals/i });

      // Initially collapsed
      await expect(journalsButton).toHaveAttribute('aria-expanded', 'false');
      await expect(page.getByRole('link', { name: 'Etc' })).not.toBeVisible();

      // Click to expand
      await journalsButton.click();
      await expect(journalsButton).toHaveAttribute('aria-expanded', 'true');
      await expect(page.getByRole('link', { name: 'Etc' })).toBeVisible();

      // Click to collapse
      await journalsButton.click();
      await expect(journalsButton).toHaveAttribute('aria-expanded', 'false');
      await expect(page.getByRole('link', { name: 'Etc' })).not.toBeVisible();
    });

    test('highlights active navigation item', async ({
      authenticatedPage: page,
    }) => {
      // Set viewport to desktop size
      await page.setViewportSize({ width: 1024, height: 768 });

      // Navigate to contacts page
      await page.goto('/contacts');
      await expect(page).toHaveTitle(/Personal Management System/);

      // Wait for sidebar to be fully loaded
      await page.waitForSelector('[role="navigation"]', { timeout: 10000 });

      // Current page should be highlighted (we're on /contacts)
      const allLink = page.getByTestId('nav-link-all');
      await expect(allLink).toBeVisible({ timeout: 10000 });
      await expect(allLink).toHaveAttribute('aria-current', 'page');

      // Navigate to favourites
      await page.getByRole('link', { name: 'Favourites' }).click();
      await page.waitForURL('/contacts/favourites');

      // Favourites should now be highlighted
      const favouritesLink = page.getByRole('link', { name: 'Favourites' });
      await expect(favouritesLink).toHaveAttribute('aria-current', 'page');

      // All should no longer be highlighted
      await expect(page.getByTestId('nav-link-all')).not.toHaveAttribute(
        'aria-current',
        'page'
      );
    });

    test('navigation links work correctly', async ({
      authenticatedPage: page,
    }) => {
      await page.setViewportSize({ width: 1024, height: 768 });
      await page.goto('/contacts');

      // Test navigation to different sections
      await page.getByTestId('nav-link-favourites').click();
      await expect(page).toHaveURL('/contacts/favourites');

      // Test dynamic tag navigation (if any tags exist)
      const tagLinks = page.locator('a[href*="/contacts/tags/"]');
      const tagCount = await tagLinks.count();

      if (tagCount > 0) {
        // Click the first tag link
        const firstTagLink = tagLinks.first();
        const href = await firstTagLink.getAttribute('href');
        await firstTagLink.click();
        await expect(page).toHaveURL(href!);
      }

      await page.getByTestId('nav-link-all').click();
      await expect(page).toHaveURL('/contacts');
    });
  });

  test.describe('Mobile Sidebar', () => {
    test('hides desktop sidebar and shows mobile trigger on mobile', async ({
      authenticatedPage: page,
    }) => {
      // Set viewport to mobile size
      await page.setViewportSize({ width: 375, height: 667 });
      await page.goto('/contacts');

      // Desktop sidebar should be hidden
      const desktopSidebar = page.getByTestId('sidebar');
      await expect(desktopSidebar).not.toBeVisible();

      // Mobile trigger should be visible
      const mobileTrigger = page.getByTestId('mobile-nav-trigger');
      await expect(mobileTrigger).toBeVisible();
    });

    test('opens mobile sidebar when trigger is clicked', async ({
      authenticatedPage: page,
    }) => {
      await page.setViewportSize({ width: 375, height: 667 });
      await page.goto('/contacts');

      // Click mobile trigger
      const mobileTrigger = page.getByTestId('mobile-nav-trigger');
      await mobileTrigger.click();

      // Sheet should open with navigation
      await expect(page.getByText('Navigation')).toBeVisible();
      await expect(
        page.getByRole('button', { name: /contacts/i })
      ).toBeVisible();
      await expect(
        page.getByRole('button', { name: /journals/i })
      ).toBeVisible();
    });

    test('closes mobile sidebar when navigation item is clicked', async ({
      authenticatedPage: page,
    }) => {
      await page.setViewportSize({ width: 375, height: 667 });
      await page.goto('/contacts');

      // Open mobile sidebar
      await page.getByTestId('mobile-nav-trigger').click();
      await expect(page.getByText('Navigation')).toBeVisible();

      // Click on a navigation item in the mobile sidebar
      await page
        .locator('[role="dialog"]')
        .getByTestId('nav-link-favourites')
        .click();

      // Should navigate and close sidebar
      await expect(page).toHaveURL('/contacts/favourites');
      await expect(page.getByText('Navigation')).not.toBeVisible();
    });

    // TODO: Re-enable when mobile modal viewport issues are resolved
    test.skip('mobile sidebar has same functionality as desktop', async ({
      authenticatedPage: page,
    }) => {
      // Test skipped - mobile modal has viewport interaction issues
    });
  });

  test.describe('Responsive Behavior', () => {
    test('switches between desktop and mobile sidebar based on viewport', async ({
      authenticatedPage: page,
    }) => {
      // Start with desktop
      await page.setViewportSize({ width: 1024, height: 768 });
      await page.goto('/contacts');
      await expect(page.getByTestId('sidebar')).toBeVisible();
      await expect(page.getByTestId('mobile-nav-trigger')).not.toBeVisible();

      // Switch to mobile
      await page.setViewportSize({ width: 375, height: 667 });
      await expect(page.getByTestId('sidebar')).not.toBeVisible();
      await expect(page.getByTestId('mobile-nav-trigger')).toBeVisible();

      // Switch back to desktop
      await page.setViewportSize({ width: 1024, height: 768 });
      await expect(page.getByTestId('sidebar')).toBeVisible();
      await expect(page.getByTestId('mobile-nav-trigger')).not.toBeVisible();
    });

    test('maintains navigation state across viewport changes', async ({
      authenticatedPage: page,
    }) => {
      // Start with desktop and expand journals
      await page.setViewportSize({ width: 1024, height: 768 });
      await page.goto('/contacts');
      await page.getByRole('button', { name: /journals/i }).click();
      await expect(page.getByRole('link', { name: 'Etc' })).toBeVisible();

      // Switch to mobile
      await page.setViewportSize({ width: 375, height: 667 });
      await page.getByTestId('mobile-nav-trigger').click();

      // Journals should still be expanded
      await expect(
        page.getByRole('button', { name: /journals/i })
      ).toHaveAttribute('aria-expanded', 'true');
      await expect(page.getByRole('link', { name: 'Etc' })).toBeVisible();
    });
  });

  test.describe('Accessibility', () => {
    test('has proper ARIA attributes', async ({ authenticatedPage: page }) => {
      await page.setViewportSize({ width: 1024, height: 768 });
      await page.goto('/contacts');

      // Wait for sidebar to be fully loaded
      await page.waitForSelector('[role="navigation"]', { timeout: 10000 });

      // Check main navigation has proper role and label
      const nav = page.getByRole('navigation', { name: 'Main navigation' });
      await expect(nav).toBeVisible({ timeout: 10000 });

      // Check section buttons have proper ARIA attributes
      const contactsButton = page.getByRole('button', { name: /contacts/i });
      await expect(contactsButton).toBeVisible({ timeout: 10000 });
      await expect(contactsButton).toHaveAttribute('aria-expanded');
      await expect(contactsButton).toHaveAttribute(
        'aria-controls',
        'section-contacts'
      );
    });

    test('supports keyboard navigation', async ({
      authenticatedPage: page,
    }) => {
      await page.setViewportSize({ width: 1024, height: 768 });
      await page.goto('/contacts');

      // Wait for sidebar to be fully loaded
      await page.waitForSelector('[role="navigation"]', { timeout: 10000 });

      // Wait for the "All" link to be available (ensures sidebar content is loaded)
      const allLink = page.getByTestId('nav-link-all');
      await expect(allLink).toBeVisible({ timeout: 15000 });

      // Focus on contacts button (should be expanded by default)
      const contactsButton = page.getByRole('button', { name: /contacts/i });
      await contactsButton.focus();
      await expect(contactsButton).toBeFocused();
      await expect(contactsButton).toHaveAttribute('aria-expanded', 'true');

      // Tab to navigation links (already visible since expanded by default)
      await page.keyboard.press('Tab');
      await expect(allLink).toBeFocused({ timeout: 10000 });
    });
  });
});
