import { test, expect } from '@playwright/test';

test.describe('Sidebar Navigation', () => {
  test.beforeEach(async ({ page }) => {
    // Set environment variable to disable authentication for testing
    await page.addInitScript(() => {
      window.localStorage.setItem('DISABLE_AUTH', 'true');
    });

    // Navigate to the contacts page (which should show the sidebar)
    await page.goto('/contacts');

    // Wait for the page to load
    await page.waitForLoadState('networkidle');
  });

  test.describe('Desktop Sidebar', () => {
    test('displays sidebar navigation on desktop', async ({ page }) => {
      // Set viewport to desktop size
      await page.setViewportSize({ width: 1024, height: 768 });

      // Check that desktop sidebar is visible
      const desktopSidebar = page.getByRole('complementary', {
        name: 'Desktop navigation sidebar',
      });
      await expect(desktopSidebar).toBeVisible();

      // Check navigation sections are present
      await expect(
        page.getByRole('button', { name: /contacts/i })
      ).toBeVisible();
      await expect(
        page.getByRole('button', { name: /journals/i })
      ).toBeVisible();
    });

    test('shows contacts section expanded by default', async ({ page }) => {
      await page.setViewportSize({ width: 1024, height: 768 });

      // Contacts section should be expanded
      const contactsButton = page.getByRole('button', { name: /contacts/i });
      await expect(contactsButton).toHaveAttribute('aria-expanded', 'true');

      // Contact navigation items should be visible
      await expect(page.getByRole('link', { name: 'All' })).toBeVisible();
      await expect(
        page.getByRole('link', { name: 'Favourites' })
      ).toBeVisible();
      await expect(page.getByRole('link', { name: 'Group 1' })).toBeVisible();
      await expect(page.getByRole('link', { name: 'Group 2' })).toBeVisible();
    });

    test('shows journals section collapsed by default', async ({ page }) => {
      await page.setViewportSize({ width: 1024, height: 768 });

      // Journals section should be collapsed
      const journalsButton = page.getByRole('button', { name: /journals/i });
      await expect(journalsButton).toHaveAttribute('aria-expanded', 'false');

      // Journal navigation items should not be visible
      await expect(page.getByRole('link', { name: 'Etc' })).not.toBeVisible();
    });

    test('can toggle section expansion', async ({ page }) => {
      await page.setViewportSize({ width: 1024, height: 768 });

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

    test('highlights active navigation item', async ({ page }) => {
      await page.setViewportSize({ width: 1024, height: 768 });

      // Current page should be highlighted (we're on /contacts)
      const allLink = page.getByRole('link', { name: 'All' });
      await expect(allLink).toHaveAttribute('aria-current', 'page');

      // Navigate to favourites
      await page.getByRole('link', { name: 'Favourites' }).click();
      await page.waitForURL('/contacts/favourites');

      // Favourites should now be highlighted
      const favouritesLink = page.getByRole('link', { name: 'Favourites' });
      await expect(favouritesLink).toHaveAttribute('aria-current', 'page');

      // All should no longer be highlighted
      await expect(page.getByRole('link', { name: 'All' })).not.toHaveAttribute(
        'aria-current',
        'page'
      );
    });

    test('navigation links work correctly', async ({ page }) => {
      await page.setViewportSize({ width: 1024, height: 768 });

      // Test navigation to different sections
      await page.getByRole('link', { name: 'Favourites' }).click();
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

      await page.getByRole('link', { name: 'All' }).click();
      await expect(page).toHaveURL('/contacts');
    });
  });

  test.describe('Mobile Sidebar', () => {
    test('hides desktop sidebar and shows mobile trigger on mobile', async ({
      page,
    }) => {
      // Set viewport to mobile size
      await page.setViewportSize({ width: 375, height: 667 });

      // Desktop sidebar should be hidden
      const desktopSidebar = page.getByRole('complementary', {
        name: 'Desktop navigation sidebar',
      });
      await expect(desktopSidebar).not.toBeVisible();

      // Mobile trigger should be visible
      const mobileTrigger = page.getByRole('button', {
        name: 'Open navigation menu',
      });
      await expect(mobileTrigger).toBeVisible();
    });

    test('opens mobile sidebar when trigger is clicked', async ({ page }) => {
      await page.setViewportSize({ width: 375, height: 667 });

      // Click mobile trigger
      const mobileTrigger = page.getByRole('button', {
        name: 'Open navigation menu',
      });
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
      page,
    }) => {
      await page.setViewportSize({ width: 375, height: 667 });

      // Open mobile sidebar
      await page.getByRole('button', { name: 'Open navigation menu' }).click();
      await expect(page.getByText('Navigation')).toBeVisible();

      // Click on a navigation item
      await page.getByRole('link', { name: 'Favourites' }).click();

      // Should navigate and close sidebar
      await expect(page).toHaveURL('/contacts/favourites');
      await expect(page.getByText('Navigation')).not.toBeVisible();
    });

    test('mobile sidebar has same functionality as desktop', async ({
      page,
    }) => {
      await page.setViewportSize({ width: 375, height: 667 });

      // Open mobile sidebar
      await page.getByRole('button', { name: 'Open navigation menu' }).click();

      // Test section expansion
      const journalsButton = page.getByRole('button', { name: /journals/i });
      await expect(journalsButton).toHaveAttribute('aria-expanded', 'false');

      await journalsButton.click();
      await expect(journalsButton).toHaveAttribute('aria-expanded', 'true');
      await expect(page.getByRole('link', { name: 'Etc' })).toBeVisible();
    });
  });

  test.describe('Responsive Behavior', () => {
    test('switches between desktop and mobile sidebar based on viewport', async ({
      page,
    }) => {
      // Start with desktop
      await page.setViewportSize({ width: 1024, height: 768 });
      await expect(
        page.getByRole('complementary', { name: 'Desktop navigation sidebar' })
      ).toBeVisible();
      await expect(
        page.getByRole('button', { name: 'Open navigation menu' })
      ).not.toBeVisible();

      // Switch to mobile
      await page.setViewportSize({ width: 375, height: 667 });
      await expect(
        page.getByRole('complementary', { name: 'Desktop navigation sidebar' })
      ).not.toBeVisible();
      await expect(
        page.getByRole('button', { name: 'Open navigation menu' })
      ).toBeVisible();

      // Switch back to desktop
      await page.setViewportSize({ width: 1024, height: 768 });
      await expect(
        page.getByRole('complementary', { name: 'Desktop navigation sidebar' })
      ).toBeVisible();
      await expect(
        page.getByRole('button', { name: 'Open navigation menu' })
      ).not.toBeVisible();
    });

    test('maintains navigation state across viewport changes', async ({
      page,
    }) => {
      // Start with desktop and expand journals
      await page.setViewportSize({ width: 1024, height: 768 });
      await page.getByRole('button', { name: /journals/i }).click();
      await expect(page.getByRole('link', { name: 'Etc' })).toBeVisible();

      // Switch to mobile
      await page.setViewportSize({ width: 375, height: 667 });
      await page.getByRole('button', { name: 'Open navigation menu' }).click();

      // Journals should still be expanded
      await expect(
        page.getByRole('button', { name: /journals/i })
      ).toHaveAttribute('aria-expanded', 'true');
      await expect(page.getByRole('link', { name: 'Etc' })).toBeVisible();
    });
  });

  test.describe('Accessibility', () => {
    test('has proper ARIA attributes', async ({ page }) => {
      await page.setViewportSize({ width: 1024, height: 768 });

      // Check main navigation has proper role and label
      const nav = page.getByRole('navigation', { name: 'Main navigation' });
      await expect(nav).toBeVisible();

      // Check section buttons have proper ARIA attributes
      const contactsButton = page.getByRole('button', { name: /contacts/i });
      await expect(contactsButton).toHaveAttribute('aria-expanded');
      await expect(contactsButton).toHaveAttribute(
        'aria-controls',
        'section-contacts'
      );
    });

    test('supports keyboard navigation', async ({ page }) => {
      await page.setViewportSize({ width: 1024, height: 768 });

      // Focus on contacts button
      const contactsButton = page.getByRole('button', { name: /contacts/i });
      await contactsButton.focus();
      await expect(contactsButton).toBeFocused();

      // Should be able to activate with Enter
      await page.keyboard.press('Enter');
      await expect(contactsButton).toHaveAttribute('aria-expanded', 'false');

      // Tab to navigation links
      await page.keyboard.press('Tab');
      const allLink = page.getByRole('link', { name: 'All' });
      await expect(allLink).toBeFocused();
    });
  });
});
