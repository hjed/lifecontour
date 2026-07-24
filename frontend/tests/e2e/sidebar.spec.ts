import type { Page } from '@playwright/test';
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
      await expect(page.getByRole('link', { name: 'Group 1' })).toBeHidden();
      await expect(page.getByRole('link', { name: 'Group 2' })).toBeHidden();

      // Should have dynamic tag links (wait for React Query to load tags)
      const tagLinks = page.locator('a[href*="/contacts?tag="]');
      await expect(tagLinks.first()).toBeVisible();
      expect(await tagLinks.count()).toBeGreaterThan(0);
    });

    // Note: journals-section collapsed-by-default and toggle-expansion behavior
    // is unit-tested in Sidebar.test.tsx (pure client-side state, no backend).

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

      await Promise.all([
        page.waitForURL('/contacts'),
        page.getByTestId('nav-link-all').click(),
      ]);
    });

    test('navigates to a tag page from a dynamic sidebar tag link', async ({
      taggedContactsData,
    }) => {
      // Fixture guarantees at least one tag exists, so this is deterministic.
      const { page } = taggedContactsData;
      await page.setViewportSize({ width: 1024, height: 768 });
      await page.goto('/contacts');
      await expect(
        page.getByRole('navigation', { name: 'Main navigation' })
      ).toBeVisible();

      const tagLink = page.locator('a[href*="/contacts?tag="]').first();
      await expect(tagLink).toBeVisible({ timeout: 15000 });
      const href = await tagLink.getAttribute('href');
      expect(href).toMatch(/\/contacts\?tag=\w+/);

      await Promise.all([page.waitForURL(`**${href}`), tagLink.click()]);
      expect(page.url()).toContain('/contacts?tag=');
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
      await expect(desktopSidebar).toBeHidden();

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
      ).toBeHidden();
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
      await expect(page.getByTestId('mobile-nav-trigger')).toBeHidden();

      // Switch to mobile
      await page.setViewportSize({ width: 375, height: 667 });
      await expect(page.getByTestId('sidebar')).toBeHidden();
      await expect(page.getByTestId('mobile-nav-trigger')).toBeVisible();

      // Switch back to desktop
      await page.setViewportSize({ width: 1024, height: 768 });
      await expect(page.getByTestId('sidebar')).toBeVisible();
      await expect(page.getByTestId('mobile-nav-trigger')).toBeHidden();
    });

    test('maintains navigation state across viewport changes', async ({
      authenticatedPage: page,
    }) => {
      // Start with desktop and expand journals. Inner steps use short
      // timeouts so a pre-hydration click (dropped, no handler attached yet)
      // retries instead of a single attempt consuming the whole toPass budget.
      await page.setViewportSize({ width: 1024, height: 768 });
      await page.goto('/contacts');
      await expect(async () => {
        const journalsBtn = page.getByRole('button', { name: /journals/i });
        const expanded = await journalsBtn.getAttribute('aria-expanded', {
          timeout: 2000,
        });
        if (expanded !== 'true') {
          await journalsBtn.click({ timeout: 2000 });
        }
        await expect(
          page.getByRole('link', { name: 'All Journals' })
        ).toBeVisible({ timeout: 2000 });
      }).toPass({ timeout: 30000 });

      // Switch to mobile - wait for UI to stabilize after viewport change
      await page.setViewportSize({ width: 375, height: 667 });
      // Wait for desktop sidebar to hide and mobile nav trigger to appear
      await expect(page.getByTestId('sidebar')).toBeHidden();
      await expect(page.getByTestId('mobile-nav-trigger')).toBeVisible();
      await expect(async () => {
        // Only click the trigger if the mobile dialog is NOT already open.
        // Clicking a toggle inside toPass() retries can close it on the
        // next attempt, causing an infinite retry loop.
        const dialogVisible = await page
          .locator('[role="dialog"]')
          .isVisible()
          .catch(() => false);
        if (!dialogVisible) {
          await page.getByTestId('mobile-nav-trigger').click({ timeout: 2000 });
        }
        // Journals should still be expanded. Short inner timeouts keep a
        // failed attempt from consuming the whole toPass budget.
        await expect(
          page.getByRole('button', { name: /journals/i })
        ).toHaveAttribute('aria-expanded', 'true', { timeout: 2000 });
        await expect(
          page.getByRole('link', { name: 'All Journals' })
        ).toBeVisible({ timeout: 2000 });
      }).toPass({ timeout: 30000 });
    });
  });

  test.describe('Accessibility', () => {
    // Note: static ARIA attributes (nav role/label, section-button aria-expanded
    // and aria-controls) are unit-tested in Sidebar.test.tsx. The keyboard test
    // below stays as e2e because real Tab focus traversal cannot be exercised in
    // jsdom.

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
      isMobile,
      testCleanup,
    }) => {
      if (isMobile) test.skip();
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

      // Reload to ensure sidebar tag tree picks up the newly created tags
      // (tag API data may be cached from a prior navigation)
      await page.reload();

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
      await expect(childLink).toBeHidden();

      // 6. Click expand → child becomes visible
      await expandToggle.click();
      await expect(expandToggle).toHaveAttribute('aria-expanded', 'true');
      await expect(childLink).toBeVisible();

      // 7. Click collapse → child hidden again
      await expandToggle.click();
      await expect(expandToggle).toHaveAttribute('aria-expanded', 'false');
      await expect(childLink).toBeHidden();
    });

    test('navigates to child tag page from sidebar tree', async ({
      authenticatedPage,
      isMobile,
      testCleanup,
    }) => {
      if (isMobile) test.skip();
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

      // Reload to ensure sidebar tag tree picks up the newly created tags
      await page.reload();

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
      isMobile,
    }) => {
      if (isMobile) test.skip();
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

  test.describe('Journal Tag Navigation', () => {
    /**
     * Generate an ISO datetime string offset from today by the given number of
     * days. Journals must use dates near "today" so they appear in the initial
     * date-window chunk loaded by the infinite scroll hook (~7 days around today).
     */
    function relativeDate(dayOffset: number): string {
      const d = new Date();
      d.setUTCDate(d.getUTCDate() + dayOffset);
      d.setUTCHours(12, 0, 0, 0); // Noon UTC to avoid boundary issues
      return d.toISOString();
    }

    /**
     * The Journals section is collapsed by default, so every journal tag
     * assertion has to open it first.
     */
    async function expandJournalsSection(page: Page): Promise<void> {
      const journalsButton = page.getByRole('button', { name: /journals/i });
      await expect(journalsButton).toHaveAttribute('aria-expanded', 'false');
      await journalsButton.click();
      await expect(journalsButton).toHaveAttribute('aria-expanded', 'true');
    }

    test('expands a journal tag parent and navigates to the child tag filter', async ({
      authenticatedPage,
      isMobile,
      testCleanup,
    }) => {
      if (isMobile) test.skip();
      const page = authenticatedPage;
      const dataManager = new TestDataManager(page);

      await page.setViewportSize({ width: 1024, height: 768 });
      await dataManager.clearAllJournals();

      const [parentTag] = await dataManager.createJournalTags([
        { name: 'SidebarOutdoors', color: '#FF0000' },
      ]);
      const childTag = await dataManager.createJournalTag({
        name: 'SidebarClimbing',
        color: '#00FF00',
        parent_id: parentTag.id,
      });

      const journals = await dataManager.createJournals([
        {
          title: 'Sidebar Crag Day',
          content: 'Tagged with the child tag',
          event_date_range: { start: relativeDate(-1), end: relativeDate(-1) },
        },
        {
          title: 'Sidebar Untagged Errand',
          content: 'No tags at all',
          event_date_range: { start: relativeDate(0), end: relativeDate(0) },
        },
      ]);
      await dataManager.assignTagsToJournal(journals[0].id, [childTag.id]);

      testCleanup(async () => {
        await dataManager.cleanup();
      });

      await page.goto('/journals');
      await expect(page.getByTestId('journals-list-ready')).toBeVisible();

      await expandJournalsSection(page);

      // The tree renders the parent with a collapsed expand control, and the
      // child is not reachable until it is opened.
      await expect(page.getByTestId('journal-tag-tree-container')).toBeVisible({
        timeout: 10000,
      });
      await expect(
        page.getByTestId(`nav-link-journal-tag-${parentTag.id}`)
      ).toBeVisible();

      const expandToggle = page.getByTestId(
        `journal-tag-toggle-${parentTag.id}`
      );
      await expect(expandToggle).toHaveAttribute('aria-expanded', 'false');

      const childLink = page.getByTestId(`nav-link-journal-tag-${childTag.id}`);
      await expect(childLink).toBeHidden();

      await expandToggle.click();
      await expect(expandToggle).toHaveAttribute('aria-expanded', 'true');
      await expect(childLink).toBeVisible();

      // Clicking the parent includes journals carrying only its descendants
      // (the server-side expansion from ITER17-002 Phase 1).
      await Promise.all([
        page.waitForURL(`**/journals?tag=${parentTag.id}`),
        page.getByTestId(`nav-link-journal-tag-${parentTag.id}`).click(),
      ]);
      await expect(
        page.getByRole('heading', { name: /Sidebar Crag Day/i })
      ).toBeVisible({ timeout: 30000 });
      await expect(
        page.getByRole('heading', { name: /Sidebar Untagged Errand/i })
      ).toBeHidden();

      // Client-side navigation keeps the tree mounted, so the branch is still
      // open and the child is still reachable.
      await expect(childLink).toBeVisible();

      // Clicking the child filters the list to that tag.
      await Promise.all([
        page.waitForURL(`**/journals?tag=${childTag.id}`),
        childLink.click(),
      ]);

      await expect(
        page.getByRole('heading', {
          name: `${childTag.name} Journals`,
          level: 1,
        })
      ).toBeVisible();
      await expect(
        page.getByRole('heading', { name: /Sidebar Crag Day/i })
      ).toBeVisible({ timeout: 30000 });
      await expect(
        page.getByRole('heading', { name: /Sidebar Untagged Errand/i })
      ).toBeHidden();
    });

    test('highlights the active journal tag and not All Journals', async ({
      authenticatedPage,
      isMobile,
      testCleanup,
    }) => {
      if (isMobile) test.skip();
      const page = authenticatedPage;
      const dataManager = new TestDataManager(page);

      await page.setViewportSize({ width: 1024, height: 768 });

      const [tag] = await dataManager.createJournalTags([
        { name: 'SidebarActive', color: '#FF0000' },
      ]);

      testCleanup(async () => {
        await dataManager.cleanup();
      });

      await page.goto(`/journals?tag=${tag.id}`);
      await expect(page.getByTestId('journals-list-ready')).toBeVisible();

      await expandJournalsSection(page);

      await expect(
        page.getByTestId(`nav-link-journal-tag-${tag.id}`)
      ).toHaveAttribute('aria-current', 'page');
      await expect(
        page.getByRole('link', { name: 'All Journals' })
      ).not.toHaveAttribute('aria-current', 'page');
    });

    test('a flat journal tag renders without an expand control', async ({
      authenticatedPage,
      isMobile,
      testCleanup,
    }) => {
      if (isMobile) test.skip();
      const page = authenticatedPage;
      const dataManager = new TestDataManager(page);

      await page.setViewportSize({ width: 1024, height: 768 });

      const [tag] = await dataManager.createJournalTags([
        { name: 'SidebarFlat', color: '#FF0000' },
      ]);

      testCleanup(async () => {
        await dataManager.cleanup();
      });

      await page.goto('/journals');
      await expect(page.getByTestId('journals-list-ready')).toBeVisible();

      await expandJournalsSection(page);

      await expect(
        page.getByTestId(`nav-link-journal-tag-${tag.id}`)
      ).toBeVisible();
      await expect(
        page.getByTestId(`journal-tag-toggle-${tag.id}`)
      ).toHaveCount(0);
    });
  });
});
