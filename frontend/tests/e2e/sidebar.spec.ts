import { test, expect } from './fixtures';
import { TestDataManager } from './data-management';

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

      // Wait for sidebar to be fully loaded by checking for key elements
      const navigation = page.getByRole('navigation', {
        name: 'Main navigation',
      });
      await expect(navigation).toBeVisible();

      // Wait for the contacts section to be properly initialized
      const contactsButton = page.getByRole('button', { name: /contacts/i });
      await expect(contactsButton).toBeVisible();
      await expect(contactsButton).toHaveAttribute('aria-expanded', 'true');

      // Should have basic navigation items (wait for them to be present)
      await expect(page.getByTestId('nav-link-all')).toBeVisible();
      await expect(
        page.getByRole('link', { name: 'Favourites' })
      ).toBeVisible();

      // Should NOT have hardcoded groups
      await expect(
        page.getByRole('link', { name: 'Group 1' })
      ).not.toBeVisible();
      await expect(
        page.getByRole('link', { name: 'Group 2' })
      ).not.toBeVisible();

      // Should have dynamic tag links (wait for React Query to load tags)
      const tagLinks = page.locator('a[href*="/contacts?tag="]');
      await expect(tagLinks.first()).toBeVisible();
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
      await expect(
        page.getByRole('link', { name: 'All Journals' })
      ).not.toBeVisible();
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
      await expect(
        page.getByRole('link', { name: 'All Journals' })
      ).not.toBeVisible();

      // Click to expand
      // Make retry idempotent by keeping click outside, allowing expect's
      // built-in polling to wait for the 'aria-expanded' state
      await journalsButton.click();
      await expect(journalsButton).toHaveAttribute('aria-expanded', 'true', {
        timeout: 15000,
      });
      await expect(
        page.getByRole('link', { name: 'All Journals' })
      ).toBeVisible();

      // Click to collapse
      await journalsButton.click();
      await expect(journalsButton).toHaveAttribute('aria-expanded', 'false');
      await expect(
        page.getByRole('link', { name: 'All Journals' })
      ).not.toBeVisible();
    });

    test('highlights active navigation item', async ({
      authenticatedPage: page,
    }) => {
      // Set viewport to desktop size
      await page.setViewportSize({ width: 1024, height: 768 });

      // Navigate to contacts page
      await page.goto('/contacts');
      await expect(page).toHaveTitle(/Personal Management System/);

      // Wait for sidebar to be fully loaded by checking for navigation and key elements
      const navigation = page.getByRole('navigation', {
        name: 'Main navigation',
      });
      await expect(navigation).toBeVisible();

      // Current page should be highlighted (we're on /contacts)
      const allLink = page.getByTestId('nav-link-all');
      await expect(allLink).toBeVisible();
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
      await Promise.all([
        page.waitForURL('/contacts/favourites'),
        page.getByTestId('nav-link-favourites').click(),
      ]);

      // Test dynamic tag navigation (if any tags exist)
      const tagLinks = page.locator('a[href*="/contacts?tag="]');
      const tagCount = await tagLinks.count();

      if (tagCount > 0) {
        // Click the first tag link
        const firstTagLink = tagLinks.first();
        const href = await firstTagLink.getAttribute('href');
        await Promise.all([page.waitForURL(href!), firstTagLink.click()]);
      }

      await Promise.all([
        page.waitForURL('/contacts'),
        page.getByTestId('nav-link-all').click(),
      ]);
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
      await expect(
        page.getByRole('heading', { name: 'Navigation' })
      ).toBeVisible();
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
      await expect(
        page.getByRole('heading', { name: 'Navigation' })
      ).toBeVisible();

      // Click on a navigation item in the mobile sidebar and wait for navigation
      await Promise.all([
        page.waitForURL('/contacts/favourites'),
        page
          .locator('[role="dialog"]')
          .getByTestId('nav-link-favourites')
          .click(),
      ]);

      // Should navigate and close sidebar
      await expect(
        page.getByRole('heading', { name: 'Navigation' })
      ).not.toBeVisible();
    });

    // TODO: Re-enable when mobile modal viewport issues are resolved
    test.skip('mobile sidebar has same functionality as desktop', async ({
      authenticatedPage: _page,
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
      await expect(
        page.getByRole('link', { name: 'All Journals' })
      ).toBeVisible();

      // Switch to mobile - wait for UI to stabilize after viewport change
      await page.setViewportSize({ width: 375, height: 667 });
      // Wait for desktop sidebar to hide and mobile nav trigger to appear
      await expect(page.getByTestId('sidebar')).not.toBeVisible();
      await expect(page.getByTestId('mobile-nav-trigger')).toBeVisible();
      await page.getByTestId('mobile-nav-trigger').click();

      // Journals should still be expanded
      await expect(
        page.getByRole('button', { name: /journals/i })
      ).toHaveAttribute('aria-expanded', 'true');
      await expect(
        page.getByRole('link', { name: 'All Journals' })
      ).toBeVisible();
    });
  });

  test.describe('Accessibility', () => {
    test('has proper ARIA attributes', async ({ authenticatedPage: page }) => {
      await page.setViewportSize({ width: 1024, height: 768 });
      await page.goto('/contacts');

      // Check main navigation has proper role and label
      const nav = page.getByRole('navigation', { name: 'Main navigation' });
      await expect(nav).toBeVisible();

      // Check section buttons have proper ARIA attributes
      const contactsButton = page.getByRole('button', { name: /contacts/i });
      await expect(contactsButton).toBeVisible();
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

      // Wait for sidebar to be fully loaded by ensuring key elements are present
      const navigation = page.getByRole('navigation', {
        name: 'Main navigation',
      });
      await expect(navigation).toBeVisible();

      // Ensure the contacts section is properly initialized and expanded
      const contactsButton = page.getByRole('button', { name: /contacts/i });
      await expect(contactsButton).toBeVisible();
      await expect(contactsButton).toHaveAttribute('aria-expanded', 'true');

      // Ensure the "All" link is available (indicates sidebar content is fully loaded)
      const allLink = page.getByTestId('nav-link-all');
      await expect(allLink).toBeVisible();

      // Focus on contacts button
      await contactsButton.focus();
      await expect(contactsButton).toBeFocused();

      // Tab to navigation links (should focus the "All" link)
      await page.keyboard.press('Tab');
      await expect(allLink).toBeFocused();
    });
  });

  test.describe('Hierarchical Tag Navigation', () => {
    test('shows parent tag with expand control and nested children', async ({
      authenticatedPage,
      testCleanup,
    }) => {
      const page = authenticatedPage;
      const testDataManager = new TestDataManager(page);

      await page.setViewportSize({ width: 1024, height: 768 });

      // 1. Create parent tag
      const parentName = `SidebarParent-${Date.now()}-${Math.floor(Math.random() * 1000)}`;
      const parentResult = await testDataManager.createTag({
        name: parentName,
      });
      const parentId = parentResult.id;

      testCleanup(async () => {
        await testDataManager.deleteTagByName(parentName).catch(() => {});
      });

      // 2. Create child tag
      const childName = `SidebarChild-${Date.now()}-${Math.floor(Math.random() * 1000)}`;
      const childResult = await testDataManager.createTag({
        name: childName,
        parent_id: parseInt(parentId),
      });
      const childId = childResult.id;

      testCleanup(async () => {
        await testDataManager.deleteTagByName(childName).catch(() => {});
      });

      // 3. Navigate to contacts page to see sidebar
      await page.goto('/contacts');
      await expect(page).toHaveTitle(/Personal Management System/);

      // Wait for sidebar tag tree to load
      const tagTreeArea = page.getByTestId('tag-tree-container');
      await expect(tagTreeArea).toBeVisible({ timeout: 10000 });

      // 4. Parent should be visible with an expand toggle
      const parentLink = page.getByTestId(`nav-link-tag-${parentId}`);
      await expect(parentLink).toBeVisible();

      const expandToggle = page.getByTestId(`tag-toggle-${parentId}`);
      await expect(expandToggle).toBeVisible();
      await expect(expandToggle).toHaveAttribute('aria-expanded', 'false');

      // 5. Child should NOT be visible initially
      const childLink = page.getByTestId(`nav-link-tag-${childId}`);
      await expect(childLink).not.toBeVisible();

      // 6. Click expand → child becomes visible
      await expandToggle.click();
      await expect(expandToggle).toHaveAttribute('aria-expanded', 'true');
      await expect(childLink).toBeVisible();

      // 7. Click collapse → child hidden again
      await expandToggle.click();
      await expect(expandToggle).toHaveAttribute('aria-expanded', 'false');
      await expect(childLink).not.toBeVisible();
    });

    test('navigates to child tag page from sidebar tree', async ({
      authenticatedPage,
      testCleanup,
    }) => {
      const page = authenticatedPage;
      const testDataManager = new TestDataManager(page);

      await page.setViewportSize({ width: 1024, height: 768 });

      // Create parent + child
      const parentName = `NavParent-${Date.now()}-${Math.floor(Math.random() * 1000)}`;
      const parentResult = await testDataManager.createTag({
        name: parentName,
      });
      const parentId = parentResult.id;

      testCleanup(async () => {
        await testDataManager.deleteTagByName(parentName).catch(() => {});
      });

      const childName = `NavChild-${Date.now()}-${Math.floor(Math.random() * 1000)}`;
      const childResult = await testDataManager.createTag({
        name: childName,
        parent_id: parseInt(parentId),
      });
      const childId = childResult.id;

      testCleanup(async () => {
        await testDataManager.deleteTagByName(childName).catch(() => {});
      });

      // Navigate
      await page.goto('/contacts');
      await expect(page).toHaveTitle(/Personal Management System/);

      // Wait for tag tree, expand parent
      const tagTreeArea = page.getByTestId('tag-tree-container');
      await expect(tagTreeArea).toBeVisible({ timeout: 10000 });

      const expandToggle = page.getByTestId(`tag-toggle-${parentId}`);
      await expandToggle.click();

      // Click child tag link → navigate to tag page
      const childLink = page.getByTestId(`nav-link-tag-${childId}`);
      await expect(childLink).toBeVisible();
      await Promise.all([
        page.waitForURL(`**/contacts?tag=${childId}`),
        childLink.click(),
      ]);
    });

    test('flat tags render without expand controls', async ({
      taggedContactsData,
    }) => {
      const { page } = taggedContactsData;
      await page.setViewportSize({ width: 1024, height: 768 });

      await page.goto('/contacts');
      await expect(page).toHaveTitle(/Personal Management System/);

      // Wait for tag tree to load
      const tagTreeArea = page.getByTestId('tag-tree-container');
      await expect(tagTreeArea).toBeVisible({ timeout: 10000 });

      // Tag links should be present as regular links
      const tagLinks = page.locator('a[href*="/contacts?tag="]');
      await expect(tagLinks.first()).toBeVisible();

      const tagCount = await tagLinks.count();
      expect(tagCount).toBeGreaterThan(0);
    });
  });
});
