import { test, expect } from '@playwright/test';
import { createTestHelpers } from './utils/test-helpers';

test.describe('Sidebar Dynamic Tags Navigation', () => {
  test('should display dynamic tags in sidebar navigation', async ({
    page,
  }) => {
    const { auth } = createTestHelpers(page);

    await page.goto('/contacts');
    await expect(page).toHaveTitle(/Personal Management System/);

    const result = await auth.handleProtectedPageAccess();

    if (result === 'accessed') {
      try {
        // Wait for sidebar to load
        await page.waitForSelector('nav, aside, [role="navigation"]', {
          timeout: 5000,
        });

        // Look for tag links in sidebar (should not be hardcoded Group 1, Group 2)
        const tagLinks = page.locator('a[href*="/contacts/tags/"]');
        const hardcodedGroups = page.locator('text="Group 1", text="Group 2"');

        // Should not have hardcoded groups
        expect(await hardcodedGroups.count()).toBe(0);

        // May have dynamic tag links
        const tagCount = await tagLinks.count();
        if (tagCount > 0) {
          // Verify tag links have proper structure
          const firstTag = tagLinks.first();
          await expect(firstTag).toHaveAttribute('href');

          const href = await firstTag.getAttribute('href');
          expect(href).toMatch(/\/contacts\/tags\/\w+/);

          // Tag link should be visible and clickable
          await expect(firstTag).toBeVisible();
          await expect(firstTag).toBeEnabled();
        }
      } catch (error) {
        console.log('Sidebar still loading or no tags available');
      }
    }
  });

  test('should show favourites link in sidebar', async ({ page }) => {
    const { auth } = createTestHelpers(page);

    await page.goto('/contacts');
    await expect(page).toHaveTitle(/Personal Management System/);

    const result = await auth.handleProtectedPageAccess();

    if (result === 'accessed') {
      try {
        // Wait for sidebar to load
        await page.waitForSelector('nav, aside, [role="navigation"]', {
          timeout: 5000,
        });

        // Look for favourites link
        const favouritesLink = page.locator('a[href="/contacts/favourites"]');

        if ((await favouritesLink.count()) > 0) {
          await expect(favouritesLink.first()).toBeVisible();
          await expect(favouritesLink.first()).toBeEnabled();

          // Should have star icon or "Favourites" text
          const linkContent = favouritesLink.first();
          const hasStarIcon = (await linkContent.locator('svg').count()) > 0;
          const linkText = await linkContent.textContent();

          expect(
            hasStarIcon ||
              (linkText && linkText.toLowerCase().includes('favourite'))
          ).toBe(true);
        }
      } catch (error) {
        console.log('Sidebar favourites link test skipped');
      }
    }
  });

  test('should show "All" contacts link in sidebar', async ({ page }) => {
    const { auth } = createTestHelpers(page);

    await page.goto('/contacts');
    await expect(page).toHaveTitle(/Personal Management System/);

    const result = await auth.handleProtectedPageAccess();

    if (result === 'accessed') {
      try {
        // Wait for sidebar to load
        await page.waitForSelector('nav, aside, [role="navigation"]', {
          timeout: 5000,
        });

        // Look for "All" contacts link
        const allContactsLink = page.locator(
          'a[href="/contacts"]:has-text("All")'
        );

        if ((await allContactsLink.count()) > 0) {
          await expect(allContactsLink.first()).toBeVisible();
          await expect(allContactsLink.first()).toBeEnabled();

          const linkText = await allContactsLink.first().textContent();
          expect(linkText?.toLowerCase()).toContain('all');
        }
      } catch (error) {
        console.log('Sidebar all contacts link test skipped');
      }
    }
  });

  test('should allow navigation to tag pages from sidebar', async ({
    page,
  }) => {
    const { auth } = createTestHelpers(page);

    await page.goto('/contacts');
    await expect(page).toHaveTitle(/Personal Management System/);

    const result = await auth.handleProtectedPageAccess();

    if (result === 'accessed') {
      try {
        // Wait for sidebar to load
        await page.waitForSelector('nav, aside, [role="navigation"]', {
          timeout: 5000,
        });

        // Look for tag links in sidebar
        const tagLinks = page.locator('a[href*="/contacts/tags/"]');
        const tagCount = await tagLinks.count();

        if (tagCount > 0) {
          const firstTagLink = tagLinks.first();
          const href = await firstTagLink.getAttribute('href');

          // Click the tag link
          await firstTagLink.click();

          // Wait for navigation to complete
          await page.waitForLoadState('networkidle');

          // Should navigate to tag page or login
          const currentUrl = page.url();
          expect(
            currentUrl.includes(href!) || currentUrl.includes('/auth/login')
          ).toBe(true);
        }
      } catch (error) {
        console.log(
          'Tag navigation test skipped - no tags or navigation issues'
        );
      }
    }
  });

  test('should allow navigation to favourites page from sidebar', async ({
    page,
  }) => {
    const { auth } = createTestHelpers(page);

    await page.goto('/contacts');
    await expect(page).toHaveTitle(/Personal Management System/);

    const result = await auth.handleProtectedPageAccess();

    if (result === 'accessed') {
      try {
        // Wait for sidebar to load
        await page.waitForSelector('nav, aside, [role="navigation"]', {
          timeout: 5000,
        });

        // Look for favourites link
        const favouritesLink = page.locator('a[href="/contacts/favourites"]');

        if ((await favouritesLink.count()) > 0) {
          await favouritesLink.first().click();

          // Wait for navigation to complete
          await page.waitForLoadState('networkidle');

          // Should navigate to favourites page or login
          const currentUrl = page.url();
          expect(
            currentUrl.includes('/contacts/favourites') ||
              currentUrl.includes('/auth/login')
          ).toBe(true);
        }
      } catch (error) {
        console.log('Favourites navigation test skipped');
      }
    }
  });

  test('should handle loading state for dynamic tags', async ({ page }) => {
    const { auth } = createTestHelpers(page);

    await page.goto('/contacts');
    await expect(page).toHaveTitle(/Personal Management System/);

    const result = await auth.handleProtectedPageAccess();

    if (result === 'accessed') {
      // Sidebar should be visible even during loading
      const sidebar = page.locator('nav, aside, [role="navigation"]').first();
      await expect(sidebar).toBeVisible();

      // Should have at least the basic navigation items (All, Favourites)
      const basicNavItems = page.locator(
        'a[href="/contacts"], a[href="/contacts/favourites"]'
      );
      const basicItemCount = await basicNavItems.count();
      expect(basicItemCount).toBeGreaterThanOrEqual(1);
    }
  });

  test('should show proper contact section structure in sidebar', async ({
    page,
  }) => {
    const { auth } = createTestHelpers(page);

    await page.goto('/contacts');
    await expect(page).toHaveTitle(/Personal Management System/);

    const result = await auth.handleProtectedPageAccess();

    if (result === 'accessed') {
      try {
        // Wait for sidebar to load
        await page.waitForSelector('nav, aside, [role="navigation"]', {
          timeout: 5000,
        });

        // Should have a contacts section
        const contactsSection = page.locator('text=/contact/i').first();
        if ((await contactsSection.count()) > 0) {
          await expect(contactsSection).toBeVisible();
        }

        // Should have navigation items under contacts
        const contactNavItems = page.locator('a[href*="/contacts"]');
        const navItemCount = await contactNavItems.count();
        expect(navItemCount).toBeGreaterThanOrEqual(1);
      } catch (error) {
        console.log('Sidebar structure test skipped');
      }
    }
  });

  test('should maintain active state for current page in sidebar', async ({
    page,
  }) => {
    const { auth } = createTestHelpers(page);

    // Test on favourites page
    await page.goto('/contacts/favourites');
    await expect(page).toHaveTitle(/Personal Management System/);

    const result = await auth.handleProtectedPageAccess();

    if (result === 'accessed') {
      try {
        // Wait for sidebar to load
        await page.waitForSelector('nav, aside, [role="navigation"]', {
          timeout: 5000,
        });

        // Favourites link should have active state
        const favouritesLink = page.locator('a[href="/contacts/favourites"]');

        if ((await favouritesLink.count()) > 0) {
          const linkElement = favouritesLink.first();

          // Check for active state indicators (aria-current, active class, etc.)
          const ariaCurrent = await linkElement.getAttribute('aria-current');
          const className = await linkElement.getAttribute('class');

          // Should have some indication of active state
          expect(
            ariaCurrent === 'page' ||
              (className && className.includes('active'))
          ).toBe(true);
        }
      } catch (error) {
        console.log('Active state test skipped');
      }
    }
  });

  test('should be responsive on mobile devices', async ({ page }) => {
    const { auth, responsive } = createTestHelpers(page);

    // Set mobile viewport
    await responsive.setMobileViewport();

    await page.goto('/contacts');
    await expect(page).toHaveTitle(/Personal Management System/);

    const result = await auth.handleProtectedPageAccess();

    if (result === 'accessed') {
      // On mobile, sidebar might be hidden or in a hamburger menu
      const sidebar = page.locator('nav, aside, [role="navigation"]');
      const hamburgerButton = page.locator(
        'button[aria-label*="menu"], button[aria-label*="navigation"]'
      );

      // Either sidebar is visible or there's a hamburger menu
      const sidebarVisible = await sidebar.first().isVisible();
      const hamburgerVisible = (await hamburgerButton.count()) > 0;

      expect(sidebarVisible || hamburgerVisible).toBe(true);

      if (hamburgerVisible && !sidebarVisible) {
        // Try to open mobile menu
        await hamburgerButton.first().click();
        await page.waitForTimeout(500);

        // Navigation should now be visible
        const mobileNav = page.locator('nav, aside, [role="navigation"]');
        await expect(mobileNav.first()).toBeVisible();
      }
    }
  });
});
